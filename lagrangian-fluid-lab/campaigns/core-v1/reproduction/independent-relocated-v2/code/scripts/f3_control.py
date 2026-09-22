"""Known forcing features in the solver's tank frame, without future fluid input.

Mirrors the version-specific JDsAccInput GPU angular branch; no reconstructed
rigid-body pose is inferred. CSV forcing can be prescribed into the future,
but integrated control velocities at t depend only on the CSV up to its bracket.
"""
import numpy as np


class AccelerationControl:
    def __init__(self,values):
        self.values=np.array(values,dtype=float,copy=True)
        a=self.values
        if a.ndim!=2 or a.shape[1]!=7 or len(a)<2 or not np.isfinite(a).all() or not np.all(np.diff(a[:,0])>0):
            raise ValueError('expected finite monotone time plus six prescribed acceleration columns')
        self.integrated=np.zeros((len(a),6))
        self.integrated[1:]=np.cumsum(np.diff(a[:,0])[:,None]*a[1:,1:],axis=0)

    @classmethod
    def from_csv(cls,path):return cls(np.loadtxt(path,delimiter=';',comments='#'))

    def at(self,t):
        if not self.values[0,0]<=t<=self.values[-1,0]:
            raise ValueError('control requested outside real input coverage')
        accel=np.array([np.interp(t,self.values[:,0],self.values[:,k]) for k in range(1,7)])
        velocity=np.array([np.interp(t,self.values[:,0],self.integrated[:,k]) for k in range(6)])
        return accel[:3],accel[3:],velocity[:3],velocity[3:]

    def body_acceleration(self,t,position,velocity,centre=(.45,0,0)):
        lin,alpha,trans,omega=self.at(t)
        p,v=np.asarray(position,float),np.asarray(velocity,float)
        if p.shape!=v.shape or p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all() or not np.isfinite(v).all():
            raise ValueError('expected finite current particle positions and velocities')
        out=np.broadcast_to(lin,p.shape).copy()
        if np.any(alpha!=0):
            r=p-centre
            out+=np.cross(alpha,r)+np.cross(omega,np.cross(omega,r))
            # Preserve actual component-specific native formula, not an assumed
            # general noninertial-frame Coriolis expression.
            out[:,0]+=2*omega[1]*v[:,2]-2*omega[2]*(v[:,1]-trans[1])
            out[:,1]+=2*omega[2]*v[:,0]-2*omega[0]*(v[:,2]-trans[2])
            out[:,2]+=2*omega[0]*v[:,1]-2*omega[1]*(v[:,0]-trans[0])
        return out
