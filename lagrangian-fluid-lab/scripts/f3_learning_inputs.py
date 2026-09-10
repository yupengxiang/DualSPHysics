"""F3-specific causal inputs for the existing ParticleMLP/local models.

This adapter consumes current predicted state and declared forcing only. It is
not the historical 115-wide cup-pose contract and does not fabricate a pose.
"""
import math
import numpy as np
import torch
from scripts.f3_control import AccelerationControl

LENGTH=.9
SPEED=math.sqrt(9.81*.09)
TIME=LENGTH/SPEED
FACES=('left','right','front','back','bottom')
FEATURE_NAMES=(
    [f'position_{a}_over_L' for a in 'xyz']+[f'velocity_{a}_over_U' for a in 'xyz']+
    [f'linear_acc_{a}_L_over_U2' for a in 'xyz']+[f'angular_acc_{a}_T2' for a in 'xyz']+
    [f'integrated_linear_velocity_{a}_over_U' for a in 'xyz']+[f'integrated_angular_velocity_{a}_T' for a in 'xyz']+
    [f'native_body_acc_{a}_L_over_U2' for a in 'xyz']+
    [f'{face}_{component}_over_L' for face in FACES for component in ('closest_dx','closest_dy','closest_dz','distance')]+
    ['elapsed_time_over_T','interval_over_T','dp_over_L','drive_amplitude','h_over_dp','artificial_viscosity','reference_density_over_1000'])


def features(position,velocity,*,time_s,interval_s,dp_m,amplitude,control):
    if position.ndim!=2 or position.shape[-1]!=3 or velocity.shape!=position.shape:
        raise ValueError('expected matching [N,3] current states')
    if velocity.device!=position.device or velocity.dtype!=position.dtype or not position.is_floating_point():
        raise ValueError('state dtype/device mismatch')
    if not torch.isfinite(position).all() or not torch.isfinite(velocity).all():
        raise ValueError('nonfinite current state is a rollout failure')
    if not all(math.isfinite(x) for x in (time_s,interval_s,dp_m,amplitude)) or interval_s<=0 or dp_m<=0 or not .9<=amplitude<=1.1:
        raise ValueError('invalid time, resolution or registered amplitude')
    lin,alpha,trans,omega=control.at(time_s)
    def tensor(x):return torch.as_tensor(x,dtype=position.dtype,device=position.device)
    n=len(position)
    raw=tensor(np.concatenate((lin*LENGTH/SPEED**2,alpha*TIME**2,trans/SPEED,omega*TIME)))
    body=tensor(lin).expand(n,3).clone()
    if np.any(alpha!=0):
        r=position-tensor([.45,0,0]);aa=tensor(alpha).expand_as(r);ww=tensor(omega).expand_as(r)
        body+=torch.linalg.cross(aa,r)+torch.linalg.cross(ww,torch.linalg.cross(ww,r))
        body[:,0]+=2*omega[1]*velocity[:,2]-2*omega[2]*(velocity[:,1]-trans[1])
        body[:,1]+=2*omega[2]*velocity[:,0]-2*omega[0]*(velocity[:,2]-trans[2])
        body[:,2]+=2*omega[0]*velocity[:,1]-2*omega[1]*(velocity[:,0]-trans[0])
    lower=tensor([-.45,-.09,0]);upper=tensor([.45,.09,.51])
    closest=torch.maximum(lower,torch.minimum(position,upper))
    wall=[]
    for axis,side in ((0,0),(0,1),(1,0),(1,1),(2,0)):
        point=closest.clone();point[:,axis]=(lower if side==0 else upper)[axis]
        delta=(point-position)/LENGTH
        wall.append(torch.cat((delta,torch.linalg.vector_norm(delta,dim=-1,keepdim=True)),dim=-1))
    scalars=tensor([time_s/TIME,interval_s/TIME,dp_m/LENGTH,amplitude,.91924*math.sqrt(3),.05,1.]).expand(n,7)
    result=torch.cat((position/LENGTH,velocity/SPEED,raw.expand(n,12),body*LENGTH/SPEED**2,*wall,scalars),dim=-1)
    assert result.shape==(n,len(FEATURE_NAMES))
    return result
