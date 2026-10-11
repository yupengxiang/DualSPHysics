"""Preparation and report-only compatibility checks for the official mDBC route.

The actual BI4 conversion remains in ``scripts/ds_data02_direct_convert.py``.
This package deliberately does not decode BI4, open HDF5, or inspect solver
payloads while preparing a request.
"""
