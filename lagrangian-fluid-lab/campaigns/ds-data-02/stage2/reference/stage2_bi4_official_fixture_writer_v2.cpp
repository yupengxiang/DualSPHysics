// Manufactured BI4 fixture for a guarded, source-bound calibration run.
//
// This program deliberately uses the repository's JPartDataBi4 writer.  It is
// not a solver output and it must never be pointed at a production case.  The
// fixture has six particles in the writer's declared contiguous role order:
// fixed[0:2], moving[2:3], fluid[3:6].  The role order is part of this tiny
// fixture contract; JPartDataBi4 itself stores role counts, not one role tag
// per particle.

#include "JPartDataBi4.h"
#include "TypesDef.h"

#include <iostream>
#include <string>

int main(int argc, char** argv){
  if(argc!=2){
    std::cerr << "usage: stage2_bi4_official_fixture_writer_v2 <output-dir>\n";
    return 2;
  }

  const std::string output_dir=argv[1];
  const unsigned np=6;

  // The first two records are fixed, the third is moving, and the last three
  // are fluid.  IDs are intentionally non-contiguous across roles so that a
  // decoder cannot pass by relying on identity values as role labels.
  const unsigned idp[np]={10u,11u,20u,100u,101u,102u};
  const tdouble3 pos[np]={
    TDouble3(-3.125,4.5,0.25),
    TDouble3(2.75,-1.5,3.125),
    TDouble3(-0.875,2.25,-4.75),
    TDouble3(1.25,2.5,3.75),
    TDouble3(-0.5,4.25,1.75),
    TDouble3(2.75,-1.25,5.5)
  };
  const tfloat3 vel[np]={
    TFloat3(0.0f,0.0f,0.0f),
    TFloat3(0.0f,0.0f,0.0f),
    TFloat3(-0.25f,0.50f,0.75f),
    TFloat3(0.75f,-1.25f,2.5f),
    TFloat3(-2.0f,3.5f,0.125f),
    TFloat3(1.25f,0.5f,-3.0f)
  };
  const float rhop[np]={997.25f,1001.5f,1004.75f,998.125f,999.875f,1002.625f};

  JPartDataBi4 writer;
  writer.ConfigBasic(
    0, 1, "STAGE2-CALIBRATION", "stage2-official-fixture",
    "stage2_bi4_official_fixture_v2", false, 0.0, output_dir
  );
  writer.ConfigParticles(
    np, 2, 1, 0, 3,
    TDouble3(0.0,0.0,0.0), TDouble3(1.0,1.0,1.0),
    false, false
  );
  writer.ConfigCtes(
    0.01, 0.02, 0.0, 1000.0, 7.0, 2.0, 0.5
  );
  writer.ConfigSimPeri(PERI_None,TDouble3(0.0),TDouble3(0.0),TDouble3(0.0));
  writer.ConfigSymmetry(false);
  writer.ConfigSplitting(false);
  writer.ConfigSimDiv(JPartDataBi4::DIV_None);
  writer.AddPartInfo(
    0, 0.125, np, 0, 0, 0.0,
    TDouble3(0.0,0.0,0.0), TDouble3(1.0,1.0,1.0), np, 102u
  );
  writer.AddPartData(np,idp,pos,vel,rhop,false);
  writer.SaveFilePart();

  std::cout << "stage2_bi4_official_fixture_v2 Part_0000.bi4 " << np << "\n";
  return 0;
}
