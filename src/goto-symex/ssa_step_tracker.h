/*******************************************************************\

Module: SSA Step Tracker

Author: Instrumentation for SSA-to-DIMACS mapping

\*******************************************************************/

#ifndef CPROVER_GOTO_SYMEX_SSA_STEP_TRACKER_H
#define CPROVER_GOTO_SYMEX_SSA_STEP_TRACKER_H

#include <cstddef>

/// Simple global to track current SSA step during conversion
/// Header-only to avoid cross-library linking issues
struct ssa_step_trackert
{
  static inline std::size_t current_step_index = 0;
  static inline bool active = false;
};

#endif // CPROVER_GOTO_SYMEX_SSA_STEP_TRACKER_H
