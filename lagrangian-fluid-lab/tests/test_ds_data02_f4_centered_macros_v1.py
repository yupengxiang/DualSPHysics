import sys
from pathlib import Path
import numpy as np,pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ds_data02_f4_centered_macros_v1 import aggregate

def test_invalid_excluded_identity_does_not_poison_native_mass():
    p=np.array([[1.,2.,3.],[np.nan]*3]);v=np.array([[2.,0.,0.],[np.nan]*3]);m=np.array([4.,np.nan]);actual=aggregate(p,v,m,np.array([True,False]));assert actual[:4]==[4.,1.,2.,3.];assert actual[7]==8.

def test_active_invalid_row_rejected():
    with pytest.raises(ValueError):aggregate(np.array([[np.nan,0,0]]),np.zeros((1,3)),np.ones(1),np.ones(1,dtype=bool))

def test_extrema_not_percentile_or_coordinate_ratio():
    p=np.array([[0,0,0],[10,2,3]],dtype=float);x=aggregate(p,np.zeros((2,3)),np.ones(2),np.ones(2,dtype=bool));assert x[1:4]==[5.,1.,1.5];assert x[8:]==[10.,2.,3.]
