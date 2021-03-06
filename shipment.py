# This file is part of the carrier_send_shipments_correos module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from correos.picking import Picking
from correos.utils import DELIVERY_OFICINA, CASHONDELIVERY_SERVICES
from trytond.modules.carrier_send_shipments.tools import unaccent, unspaces
from base64 import decodestring
from decimal import Decimal
import logging
import tempfile

__all__ = ['ShipmentOut']
logger = logging.getLogger(__name__)
_CORREOS_NACIONAL = ['ES', 'AD']


class ShipmentOut:
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.out'

    @classmethod
    def __setup__(cls):
        super(ShipmentOut, cls).__setup__()
        cls._error_messages.update({
            'correos_add_services': ('Select a service or default '
                'service in Correos API'),
            'correos_not_country': ('Add country in shipment "%(name)s" '
                'delivery address'),
            'correos_not_send_error': 'Not send shipment %(name)s. %(error)s',
            'correos_not_label': 'Not available "%(name)s" label from Correos',
            'correos_add_oficina': ('Add a office Correos to delivery '
                'or change service'),
            'correos_not_national_cashondelivery': ('Not available Correos '
                'Internation delivery and cashondelivery'),
            'correos_cashondelivery_services': ('Correos "%(service)s" service '
                'and cash on delivery is not valid. Please select an option: '
                '"%(services)s"'),
            })

    @staticmethod
    def correos_picking_data(api, shipment, service, price, weight=False,
            correos_oficina=None):
        '''
        Correos Picking Data
        :param api: obj
        :param shipment: obj
        :param service: str
        :param price: decimal
        :param weight: bol
        :param correos_oficina: str
        Return data
        '''
        Uom = Pool().get('product.uom')

        packages = shipment.number_packages
        if not packages or packages == 0:
            packages = 1

        remitente = shipment.company.party
        remitente_address = (shipment.warehouse.address or remitente.addresses[0])
        delivery_address = shipment.delivery_address

        if api.reference_origin and hasattr(shipment, 'origin'):
            code = shipment.origin and shipment.origin.rec_name or shipment.code
        else:
            code = shipment.code

        notes = ''
        if shipment.carrier_notes:
            notes = '%s\n' % shipment.carrier_notes

        data = {}
        data['TotalBultos'] = packages
        data['RemitenteNombre'] = remitente.name
        data['RemitenteNif'] = (remitente.vat_code or remitente.identifier_code)
        data['RemitenteDireccion'] = unaccent(remitente_address.street)
        data['RemitenteLocalidad'] = unaccent(remitente_address.city)
        data['RemitenteProvincia'] = (remitente_address.subdivision
            and unaccent(remitente_address.subdivision.name) or '')
        data['RemitenteCP'] = remitente_address.zip
        data['RemitenteTelefonocontacto'] = (remitente_address.phone
            or remitente.get_mechanism('phone'))
        data['RemitenteEmail'] = (remitente_address.email
            or remitente.get_mechanism('email'))
        data['DestinatarioNombre'] = unaccent(shipment.customer.name)
        data['DestinatarioDireccion'] = unaccent(delivery_address.street)
        data['DestinatarioLocalidad'] = unaccent(delivery_address.city)
        data['DestinatarioProvincia'] = (delivery_address.subdivision
            and unaccent(delivery_address.subdivision.name) or '')
        if (delivery_address.country
                and delivery_address.country.code in _CORREOS_NACIONAL):
            data['DestinatarioCP'] = delivery_address.zip
        else:
            data['DestinatarioZIP'] = delivery_address.zip
        data['DestinatarioPais'] = (delivery_address.country
            and delivery_address.country.code or '')
        data['DestinatarioTelefonocontacto'] = unspaces(shipment.phone)
        data['DestinatarioNumeroSMS'] = unspaces(shipment.mobile)
        data['DestinatarioEmail'] = unspaces(shipment.email)
        data['CodProducto'] = service.code
        data['ReferenciaCliente'] = code
        data['Observaciones1'] =  unaccent(notes)

        if shipment.carrier_cashondelivery:
            data['Reembolso'] = True
            data['TipoReembolso'] = 'RC'
            data['Importe'] = price
            data['NumeroCuenta'] = api.correos_cc

        sweight = 100
        if weight and hasattr(shipment, 'weight_func'):
            sweight = shipment.weight_func
            if sweight == 0:
                sweight = 100
            if api.weight_api_unit:
                if shipment.weight_uom:
                    sweight = Uom.compute_qty(
                        shipment.weight_uom, sweight, api.weight_api_unit)
                elif api.weight_unit:
                    sweight = Uom.compute_qty(
                        api.weight_unit, sweight, api.weight_api_unit)
        data['Peso'] = str(int(sweight))

        if correos_oficina:
            data['OficinaElegida'] = correos_oficina

        if (delivery_address.country
                and delivery_address.country.code not in _CORREOS_NACIONAL):
            data['Aduana'] = True
            data['AduanaTipoEnvio'] = api.correos_aduana_tipo_envio or '2'
            data['AduanaEnvioComercial'] = api.correos_envio_comercial or 'S'
            data['AduanaFacturaSuperiora500'] = ('S' if price > Decimal('500.00')
                else 'N')
            data['AduanaDUAConCorreos'] = api.correos_dua_con_correos or 'N'
            data['AduanaCantidad'] = str(len(shipment.outgoing_moves))
            data['AduanaDescripcion'] = api.correos_aduana_description or ''
            data['AduanaPesoneto'] = data['Peso']
            data['AduanaValorneto'] = price
        else:
            data['RemitenteNumeroSMS'] = remitente.mobile or ''

        return data

    @classmethod
    def send_correos(self, api, shipments):
        '''
        Send shipments out to correos
        :param api: obj
        :param shipments: list
        Return references, labels, errors
        '''
        pool = Pool()
        CarrierApi = pool.get('carrier.api')
        ShipmentOut = pool.get('stock.shipment.out')

        references = []
        labels = []
        errors = []

        default_service = CarrierApi.get_default_carrier_service(api)
        dbname = Transaction().database.name

        with Picking(api.username, api.password, api.correos_code,
                timeout=api.timeout, debug=api.debug) as picking_api:
            for shipment in shipments:
                service = (shipment.carrier_service or shipment.carrier.service
                    or default_service)
                if not service:
                    message = self.raise_user_error('correos_add_services', {},
                        raise_exception=False)
                    errors.append(message)
                    continue

                if (shipment.carrier_cashondelivery
                        and service.code not in CASHONDELIVERY_SERVICES):
                    message = self.raise_user_error(
                        'correos_cashondelivery_services', {
                            'service': service.code,
                            'services': ', '.join(CASHONDELIVERY_SERVICES),
                        }, raise_exception=False)
                    errors.append(message)
                    continue

                correos_oficina = None
                if service.code in DELIVERY_OFICINA:
                    if not shipment.delivery_address.correos:
                        message = self.raise_user_error('correos_add_oficina', {},
                            raise_exception=False)
                        errors.append(message)
                        continue
                    correos_oficina = shipment.delivery_address.correos

                if not shipment.delivery_address.country:
                    message = self.raise_user_error('correos_not_country', {},
                        raise_exception=False)
                    errors.append(message)
                    continue

                if (shipment.delivery_address.country.code not in _CORREOS_NACIONAL
                        and shipment.carrier_cashondelivery):
                    message = self.raise_user_error('correos_not_national_cashondelivery', {},
                        raise_exception=False)
                    errors.append(message)
                    continue

                if shipment.carrier_cashondelivery:
                    price = shipment.carrier_cashondelivery_price
                else:
                    price = shipment.total_amount_func

                data = self.correos_picking_data(
                    api, shipment, service, price, api.weight, correos_oficina)
                reference, label, error = picking_api.create(data)

                if reference:
                    self.write([shipment], {
                        'carrier_tracking_ref': reference,
                        'carrier_service': service,
                        'carrier_delivery': True,
                        'carrier_printed': True,
                        'carrier_send_date': ShipmentOut.get_carrier_date(),
                        'carrier_send_employee': ShipmentOut.get_carrier_employee() or None,
                        })
                    logger.info('Send shipment %s' % (shipment.code))
                    references.append(shipment.code)
                else:
                    logger.error('Not send shipment %s.' % (shipment.code))

                if label:
                    with tempfile.NamedTemporaryFile(
                            prefix='%s-correos-%s-' % (dbname, reference),
                            suffix='.pdf', delete=False) as temp:
                        temp.write(decodestring(label))
                    logger.info('Generated tmp label %s' % (temp.name))
                    temp.close()
                    labels.append(temp.name)
                else:
                    message = self.raise_user_error('correos_not_label', {
                            'name': shipment.rec_name,
                            }, raise_exception=False)
                    errors.append(message)
                    logger.error(message)

                if error:
                    message = self.raise_user_error('correos_not_send_error', {
                            'name': shipment.rec_name,
                            'error': error,
                            }, raise_exception=False)
                    logger.error(message)
                    errors.append(message)

        return references, labels, errors

    @classmethod
    def print_labels_correos(self, api, shipments):
        '''
        Get Correos labels from Shipment Out
        '''
        labels = []
        dbname = Transaction().database.name

        with Picking(api.username, api.password, api.correos_code,
                timeout=api.timeout, debug=api.debug) as picking_api:
            for shipment in shipments:
                if not shipment.carrier_tracking_ref:
                    logger.error(
                        'Shipment %s has not been sent by Correos.'
                        % (shipment.code))
                    continue

                reference = shipment.carrier_tracking_ref

                data = {}
                data['CodEnvio'] = reference
                label = picking_api.label(data)

                if not label:
                    logger.error(
                        'Label for shipment %s is not available from Correos.'
                        % shipment.code)
                    continue
                with tempfile.NamedTemporaryFile(
                        prefix='%s-correos-%s-' % (dbname, reference),
                        suffix='.pdf', delete=False) as temp:
                    temp.write(decodestring(label))
                logger.info(
                    'Generated tmp label %s' % (temp.name))
                temp.close()
                labels.append(temp.name)
            self.write(shipments, {'carrier_printed': True})

        return labels
