#!/usr/bin/env python3
"""Render actual saved F1 states; decimation applies only to the preview."""
import argparse
import json
from pathlib import Path

import h5py
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np


def render(source, metadata, output):
    output=Path(output)
    if output.exists():
        raise FileExistsError('preview already exists')
    geom=metadata['geometry']
    with h5py.File(source,'r') as h:
        times=h['time'][:]
        chosen=np.array([np.argmin(abs(times-t)) for t in [0.,.4,.8,float(times[-1])]])
        origin_y=h['position'][0,:,1]
        fluid_initial=h['valid'][0].astype(bool)&(h['type'][0]==3)
        initial_mass=float(h['mass'][0][fluid_initial].sum())
        fig,axes=plt.subplots(2,4,figsize=(15,6),layout='constrained')
        for column,ti in enumerate(chosen):
            valid=h['valid'][ti].astype(bool)
            fluid=valid&(h['type'][ti]==3)
            indices=np.flatnonzero(fluid)
            stride=max(1,int(np.ceil(len(indices)/6000)))
            indices=indices[::stride]
            points=h['position'][ti,indices]
            colors=np.where(origin_y[indices]<geom['tank_width_m']/2,'#2878b5','#e58e26')
            boundary_indices=np.flatnonzero(valid&(h['type'][ti]!=3))[::8]
            boundary=h['position'][ti,boundary_indices]
            for row,axis in enumerate((1,2)):
                ax=axes[row,column]
                ax.scatter(boundary[:,0],boundary[:,axis],s=1,c='#939a9f',alpha=.25,rasterized=True)
                ax.scatter(points[:,0],points[:,axis],s=2,c=colors,alpha=.65,rasterized=True)
                ax.set_xlim(-.05,geom['tank_length_m']+.05)
                ax.set_ylim(-.03,(geom['tank_width_m'] if axis==1 else geom['tank_height_m'])+.05)
                ax.set_aspect('equal',adjustable='box')
                ax.set_xlabel('x [m]');ax.set_ylabel('y [m]' if axis==1 else 'z [m]')
                ax.set_title(f't = {times[ti]:.4f} s' if row==0 else 'native side view',fontsize=10)
                if metadata['mechanism_id']=='eccentric_obstacle':
                    y=geom['obstacle_y_m'] if axis==1 else 0
                    height=geom['obstacle_width_m'] if axis==1 else geom['obstacle_height_m']
                    ax.add_patch(Rectangle((geom['obstacle_x_m'],y),geom['obstacle_length_m'],height,
                                           fill=False,edgecolor='#42484e',linewidth=1))
        fig.suptitle(f"F1 eccentric obstacle: actual saved numerical states\n"
                     f"orange/blue = initial transverse halves; initial fluid mass {initial_mass:.3f} kg; Q-N pending",fontsize=12)
        output.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(output,dpi=180)
        plt.close(fig)
        return dict(source=str(source),preview=str(output),times_s=times[chosen].tolist(),
                    initial_fluid_mass_kg=initial_mass,visual_decimation_only=True,numerical_qualification='not_assessed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--metadata',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(render(args.source,json.loads(args.metadata.read_text()),args.output),indent=2))


if __name__=='__main__':
    main()
