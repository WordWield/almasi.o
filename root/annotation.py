# ==============================================================================
# ANNOTATION
# ==============================================================================
# PURPOSE:
# Preserve ontology type addresses when storing and restoring annotations.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Resolution and representation of persistent O type expressions.
# Delegates: Python annotation interpretation, matching and casting to Core.
# ==============================================================================

import types
import typing as t

from almasi import a, o


class Annotation(a.Annotation):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Resolve trusted stored expressions against the owning ontology.
	# ----------------------------------------------------------------------
	@staticmethod
	def _resolve_source(source):
		return eval(source)

	# Retain the canonical address of a persistent class in stored expressions.
	# ----------------------------------------------------------------------
	def _get_type_source(self):
		if isinstance(self.annotation, type) and hasattr(self.annotation, '__proto__'):
			result = self.annotation.__proto__
		else:
			result = super()._get_type_source()

		return result
