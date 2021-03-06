# This file is part of the carrier_send_shipments_correos module for Tryton.
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import fields
from trytond.pool import PoolMeta
from trytond.pyson import Eval, Not, Equal
from correos.picking import *
import logging

__all__ = ['CarrierApi']


class CarrierApi:
    __metaclass__ = PoolMeta
    __name__ = 'carrier.api'
    correos_code = fields.Char('Code',
        states={
            'required': Eval('method') == 'correos',
        }, help='Correos Code (CodeEtiquetador)')
    correos_cc = fields.Char('CC',
        states={
            'required': Eval('method') == 'correos',
        }, depends=['method'], help='Correos Bank Number')
    correos_aduana_tipo_envio = fields.Char('Aduana Tipo Envio',
        states={
            'required': Eval('method') == 'correos',
        }, depends=['method'])
    correos_aduana_description = fields.Char('Aduana Description',
        states={
            'required': Eval('method') == 'correos',
        }, depends=['method'])
    correos_envio_comercial = fields.Char('Aduana Envio Comercial',
        states={
            'required': Eval('method') == 'correos',
        }, depends=['method'])
    correos_dua_con_correos = fields.Char('Aduana Dua Con Correos',
        states={
            'required': Eval('method') == 'correos',
        }, depends=['method'])

    @staticmethod
    def default_correos_aduana_tipo_envio():
        return '2'

    @staticmethod
    def default_correos_envio_comercial():
        return 'S'

    @staticmethod
    def default_correos_dua_con_correos():
        return 'N'

    @classmethod
    def get_carrier_app(cls):
        'Add Carrier Correos APP'
        res = super(CarrierApi, cls).get_carrier_app()
        res.append(('correos', 'Correos'))
        return res

    @classmethod
    def view_attributes(cls):
        return super(CarrierApi, cls).view_attributes() + [
            ('//page[@id="correos"]', 'states', {
                    'invisible': Not(Equal(Eval('method'), 'correos')),
                    })]

    @classmethod
    def test_correos(cls, api):
        'Test Correos connection'
        message = 'Connection unknown result'

        with API(api.username, api.password, api.correos_code, api.debug) as correos_api:
            message = correos_api.test_connection()
        cls.raise_user_error(message)
