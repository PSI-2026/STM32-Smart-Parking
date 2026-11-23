"""Compatibility imports; implementation lives in app.services.parking."""

from .services.parking import Admission, BusinessFault, ParkingService, canonical, tariff_bani

__all__ = ["Admission", "BusinessFault", "ParkingService", "canonical", "tariff_bani"]
