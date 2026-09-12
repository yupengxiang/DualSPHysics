import numpy as np
import pytest
import torch
from scripts.f3_local_neighbors import neighbour_indices, exact_local_summary


def oracle(x, ids):
    rows=[]
    for i in range(len(x)):
        pool=np.flatnonzero(ids!=ids[i]); distance=np.linalg.norm(x[pool]-x[i],axis=1)
        rows.append(pool[np.lexsort((ids[pool],distance))[:min(8,len(x)-1)]])
    return np.asarray(rows,dtype=np.int64)


def test_exact_identity_and_ties_under_shuffle():
    x=np.array([[i,j,k] for i in range(3) for j in range(3) for k in range(3)],dtype=float)*.01
    ids=np.arange(len(x),dtype=np.uint32)[::-1]+100
    actual,_=neighbour_indices(x,ids)
    np.testing.assert_array_equal(actual,oracle(x,ids))
    assert not (ids[actual]==ids[:,None]).any()
    order=np.random.default_rng(11).permutation(len(x))
    shuffled,_=neighbour_indices(x[order],ids[order])
    np.testing.assert_array_equal(ids[order][shuffled],ids[actual][order])


def test_coincident_distinct_ids_are_not_self():
    x=np.zeros((12,3));ids=np.arange(12,dtype=np.uint32)[::-1]
    index,d=neighbour_indices(x,ids)
    np.testing.assert_array_equal(index,oracle(x,ids))
    assert np.all(d==0)


def test_random_features_match_dense_double_oracle():
    rng=np.random.default_rng(19);x=rng.normal(size=(61,3));v=rng.normal(size=x.shape)
    ids=np.arange(len(x),dtype=np.uint32);index=oracle(x,ids)
    distance=np.linalg.norm(x[index]-x[:,None],axis=2)
    weight=1/np.maximum(distance,1e-5);weight/=weight.sum(axis=1,keepdims=True)
    want=np.concatenate(((weight[...,None]*(x[index]-x[:,None])).sum(1)/.01,
                         (weight[...,None]*(v[index]-v[:,None])).sum(1)*.002/.01,
                         distance.mean(1,keepdims=True)/.01,np.full((len(x),1),8/len(x))),axis=1)
    got=exact_local_summary(torch.tensor(x),torch.tensor(v),ids,dp_m=.01,interval_s=.002)
    np.testing.assert_allclose(got.numpy(),want,rtol=1e-14,atol=1e-14)


def test_singleton_and_invalid_ids():
    x=torch.zeros((1,3));ids=np.array([7],dtype=np.uint32)
    assert torch.equal(exact_local_summary(x,x,ids,dp_m=.01,interval_s=.01),torch.zeros((1,8)))
    with pytest.raises(ValueError):neighbour_indices(np.zeros((2,3)),np.array([1,1]))
    with pytest.raises(ValueError):neighbour_indices(np.array([[np.nan,0,0]]),ids)
