/*******************************************************************\

Module: Writing DIMACS Files

Author: Daniel Kroening, kroening@kroening.com

\*******************************************************************/

/// \file
/// Writing DIMACS Files

#include "bv_dimacs.h"

#include <util/bitvector_types.h>

#include <solvers/sat/dimacs_cnf.h>

#include <fstream> // IWYU pragma: keep
#include <iostream>

bv_dimacst::bv_dimacst(
  const namespacet &_ns,
  dimacs_cnft &_prop,
  message_handlert &message_handler,
  const std::string &_filename)
  : bv_pointerst(_ns, _prop, message_handler),
    filename(_filename),
    dimacs_cnf_prop(_prop)
{
}

bool bv_dimacst::write_dimacs()
{
  if(filename.empty() || filename == "-")
    return write_dimacs(std::cout);

  std::ofstream out(filename);

  if(!out)
  {
    log.error() << "failed to open " << filename << messaget::eom;
    return false;
  }

  return write_dimacs(out);
}

bool bv_dimacst::write_dimacs(std::ostream &out)
{
  dimacs_cnf_prop.write_dimacs_cnf(out);

  // we dump the mapping variable<->literals
  for(const auto &s : get_symbols())
  {
    if(s.second.is_constant())
      out << "c " << s.first << " " << (s.second.is_true() ? "TRUE" : "FALSE")
          << "\n";
    else
      out << "c " << s.first << " " << s.second.dimacs() << "\n";
  }

  // dump mapping for selected bit-vectors
  for(const auto &m : get_map().get_mapping())
  {
    const auto &literal_map = m.second.literal_map;

    if(literal_map.empty())
      continue;

    out << "c " << m.first;

    for(const auto &lit : literal_map)
    {
      out << ' ';

      if(lit.is_constant())
        out << (lit.is_true() ? "TRUE" : "FALSE");
      else
        out << lit.dimacs();
    }

    // Add type information
    out << " @type=" << m.second.type.id();
    if(
      m.second.type.id() == ID_signedbv ||
      m.second.type.id() == ID_unsignedbv)
    {
      out << "[" << to_bitvector_type(m.second.type).get_width() << "]";
    }

    out << "\n";
  }

  // Dump Tseitin variable mappings
  for(const auto &entry : dimacs_cnf_prop.get_tseitin_map())
  {
    const literalt &lit = entry.first;
    const cnft::tseitin_entryt &tseitin = entry.second;

    out << "c @tseitin " << lit.var_no();

    switch(tseitin.gate_type)
    {
    case cnft::gate_typet::AND:
      out << " AND";
      break;
    case cnft::gate_typet::OR:
      out << " OR";
      break;
    case cnft::gate_typet::XOR:
      out << " XOR";
      break;
    case cnft::gate_typet::ITE:
      out << " ITE";
      break;
    case cnft::gate_typet::CMP_CHAIN:
      out << " CMP_CHAIN";
      break;
    case cnft::gate_typet::CMP_RESULT:
      out << " CMP_RESULT";
      break;
    case cnft::gate_typet::CARRY:
      out << " CARRY";
      break;
    case cnft::gate_typet::SUM:
      out << " SUM";
      break;
    case cnft::gate_typet::DIVIDER:
      out << " DIVIDER";
      break;
    }

    for(const auto &input : tseitin.inputs)
      out << " " << input.dimacs();

    out << "\n";
  }

  return false;
}
