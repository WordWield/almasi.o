# ==============================================================================
# T RELOADABLE
# ==============================================================================
# Extend Almasi source reload with ontology registry and root-type constraints.
# ==============================================================================

import a
import o


class TReloadable(a.ReloadableModule):

	# Observe only ontology descendants with a persistent type parent.
	# ----------------------------------------------------------------------
	@classmethod
	def _observe_reload(cls, file):
		if '__proto__' in cls.__dict__ and cls.__parent__ is not None:
			super()._observe_reload(file)

	# Keep ontology cache publication inside the reload rollback boundary.
	# ----------------------------------------------------------------------
	@classmethod
	def __reload__(cls):
		return super().__reload__(o.services.Cache.replace)
