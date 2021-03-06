# This file is part of the carrier_send_shipments_correos module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# copyright notices and license terms. the full
from trytond.pool import Pool
from .api import *
from .address import *
from .shipment import *
from .manifest import *


def register():
    Pool.register(
        Address,
        CarrierApi,
        ShipmentOut,
        module='carrier_send_shipments_correos', type_='model')
    Pool.register(
        CarrierManifest,
        module='carrier_send_shipments_correos', type_='wizard')
