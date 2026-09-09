// Exercise the same read loop as JLinearValue(6)::LoadFile without a solver.
#include "JReadDatafile.h"
#include <cmath>
#include <iostream>
int main(int argc,char**argv){
 if(argc!=2)return 2;
 try{
  JReadDatafile f;f.LoadFile(argv[1]);unsigned rows=f.Lines()-f.RemLines();
  if(rows<2)return 3;double last=-1,first=0;
  for(unsigned i=0;i<rows;i++){
   double t=f.ReadNextDouble();if(!std::isfinite(t)||t<=last)return 4;
   if(i==0)first=t;last=t;
   for(int j=0;j<6;j++)if(!std::isfinite(f.ReadNextDouble(true)))return 5;
  }
  std::cout<<"{\"rows\":"<<rows<<",\"first_time_s\":"<<first<<",\"last_time_s\":"<<last<<"}\n";
 }catch(...){std::cerr<<"native acceleration parser rejected input\n";return 1;}
 return 0;
}
