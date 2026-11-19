# ==============================================================================
# RELOADABLE MODULE
# ==============================================================================
# PURPOSE:
# Inherit Almasi's module reload lifecycle with O's ontology specialization.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Composition of O's reload policy and Almasi's module capabilities.
# Delegates: Reload behavior to the inherited implementations.
# ==============================================================================

import a
import o


class ReloadableModule(a.ReloadableModule, o.Reloadable):
	pass
