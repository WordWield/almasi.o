# ==============================================================================
# T RELOADABLE MODULE
# ==============================================================================
# PURPOSE:
# Apply ontology-specific reload rules to source-backed type classes.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Ontology source observation and cache replacement on reload.
# Delegates: Module lifecycle, source reload and subscriptions to Almasi.
# ==============================================================================

import a


class TReloadableModule(a.ReloadableModule):

	# ==========================================================================
	# FRAMEWORK METHODS
	# ==========================================================================

	# Observe source-backed types except for the ontology root.
	# ----------------------------------------------------------------------
	@classmethod
	def _observe_reload(cls, file):
		if '__proto__' not in cls.__dict__ or cls.__parent__ is not None:
			super()._observe_reload(file)

	# Keep the ontology cache consistent with the replacement type.
	# ----------------------------------------------------------------------
	@classmethod
	def __reload__(cls):
		commit = cls.__lib__.services.Cache.replace if '__proto__' in cls.__dict__ else None
		return super().__reload__(commit)
