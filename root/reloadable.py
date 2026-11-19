# ==============================================================================
# RELOADABLE
# ==============================================================================
# PURPOSE:
# Extend Almasi reload for ontology types while preserving ordinary modules.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Ontology source observation policy and cache replacement on reload.
# Delegates: Source reload, subscriptions and rollback to Almasi.
# ==============================================================================

import a


class Reloadable(a.Reloadable, a.Module):

	# ==========================================================================
	# FRAMEWORK METHODS
	# ==========================================================================

	# Observe ordinary modules and ontology descendants, not the root type.
	# ----------------------------------------------------------------------
	@classmethod
	def _observe_reload(cls, file):
		if '__proto__' not in cls.__dict__ or cls.__parent__ is not None:
			super()._observe_reload(file)

	# Replace the ontology registry only for ontology classes.
	# ----------------------------------------------------------------------
	@classmethod
	def __reload__(cls):
		commit = cls.__lib__.services.Cache.replace if '__proto__' in cls.__dict__ else None
		return super().__reload__(commit)
