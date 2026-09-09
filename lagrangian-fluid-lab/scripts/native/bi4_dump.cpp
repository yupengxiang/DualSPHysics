// Read-only adapter using the repository's JBinaryData implementation.
#include "JBinaryData.h"
#include <fstream>
#include <iostream>
#include <sys/stat.h>
void dump(JBinaryData& d,const std::string& dir){
 mkdir(dir.c_str(), 0775);
 for(size_t i=0;i<d.GetArraysCount();i++){
  auto a=d.GetArray(i);auto ptr=a->GetDataPointer();
  std::cout<<dir<<" "<<a->GetName()<<" "<<int(a->GetType())<<" "<<a->GetCount()<<" "<<(a->GetCount()*JBinaryDataDef::SizeOfType(a->GetType()))<<"\n";
  std::ofstream f(dir+"/"+a->GetName()+".bin",std::ios::binary);f.write((const char*)ptr,(a->GetCount()*JBinaryDataDef::SizeOfType(a->GetType())));
 }
 for(size_t i=0;i<d.GetItemsCount();i++){auto child=d.GetItem(i);dump(*child,dir+"/"+child->GetName());}
}
int main(int argc,char**argv){if(argc!=3)return 2;try{JBinaryData d;d.LoadFile(argv[1],"",true);d.SaveFileXml(std::string(argv[2])+".xml",false);dump(d,argv[2]);}catch(const std::exception&e){std::cerr<<e.what();return 1;}return 0;}
