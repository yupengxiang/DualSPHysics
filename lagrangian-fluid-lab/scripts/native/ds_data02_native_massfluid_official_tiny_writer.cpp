// Tiny manufactured calibration writer for the DS-DATA-02 native MassFluid
// serialization contract.  This deliberately uses the official JBinaryData
// writer/read API and writes only the output path supplied by the caller.
// It is not a solver frame and must never be used as scientific evidence.

#include "JBinaryData.h"
#include "TypesDef.h"
#include <cstring>
#include <iomanip>
#include <iostream>

static unsigned long long Bits(double value) {
  unsigned long long bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  return bits;
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const std::string path(argv[1]);
  const double xml_massfluid = 0.000681472;
  // This is the source-observed JSph float -> JBinaryData double widening.
  const double native_massfluid = static_cast<double>(static_cast<float>(xml_massfluid));

  JBinaryData data("JPartDataBi4");
  data.SetvDouble("MassFluid", native_massfluid);
  data.SetvDouble("Dp", 0.008);
  data.SetvUllong("CaseNfluid", 2);
  JBinaryData* part = data.CreateItem("Part");
  part->SetvDouble("TimeStep", 0.125);

  const unsigned ids[2] = {100u, 101u};
  const tfloat3 positions[2] = {
    TFloat3(0.1f, 0.2f, 0.3f), TFloat3(0.4f, 0.5f, 0.6f)
  };
  const tfloat3 velocities[2] = {
    TFloat3(1.f, 2.f, 3.f), TFloat3(4.f, 5.f, 6.f)
  };
  const float density[2] = {1000.f, 1001.f};
  const float mass[2] = {float(native_massfluid), float(native_massfluid)};
  part->CreateArray("Idp", JBinaryDataDef::DatUint, 2, ids, false);
  part->CreateArray("Pos", JBinaryDataDef::DatFloat3, 2, positions, false);
  part->CreateArray("Vel", JBinaryDataDef::DatFloat3, 2, velocities, false);
  part->CreateArray("Rhop", JBinaryDataDef::DatFloat, 2, density, false);
  part->CreateArray("Mass", JBinaryDataDef::DatFloat, 2, mass, false);
  data.SaveFile(path, false, true);

  // Read back with the same official library before the external decoder is
  // invoked.  Both observations are retained by the Python worker.
  JBinaryData loaded("JPartDataBi4");
  loaded.LoadFile(path, "", true);
  JBinaryData* loaded_part = loaded.GetItem("Part");
  if (!loaded_part) return 3;
  std::cout << std::setprecision(17)
            << "writer_massfluid=" << native_massfluid
            << " writer_massfluid_bits=" << std::hex << Bits(native_massfluid) << std::dec
            << " reader_massfluid=" << loaded.GetvDouble("MassFluid")
            << " idp_count=" << loaded_part->GetArray("Idp")->GetCount()
            << " pos_type=" << JBinaryDataDef::TypeToStr(loaded_part->GetArray("Pos")->GetType())
            << " vel_type=" << JBinaryDataDef::TypeToStr(loaded_part->GetArray("Vel")->GetType())
            << " rhop_type=" << JBinaryDataDef::TypeToStr(loaded_part->GetArray("Rhop")->GetType())
            << " mass_type=" << JBinaryDataDef::TypeToStr(loaded_part->GetArray("Mass")->GetType())
            << "\n";
  return 0;
}
