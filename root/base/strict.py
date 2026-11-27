# ==============================================================================
# STRICT
# ==============================================================================
# PURPOSE:
# Extend strict Python calls with O's existing data representation.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Explicit typed data boundaries.
# Delegates: Method checks to Core, conversion and schema projection to O.
# ==============================================================================

import json

from jsonschema  import Draft202012Validator
from referencing import Registry

from almasi import a, o


class Strict(a.base.Strict):

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Publish an existing O type schema, not a second representation.
	# ----------------------------------------------------------------------
	@staticmethod
	def strict_schema(data_type):
		'''Return JSON Schema for a concrete O type or type(None).'''
		if data_type is type(None):
			result = {'type': 'null'}
		elif isinstance(data_type, type) and data_type is not o.T and issubclass(data_type, o.T):
			result = data_type.to_json_schema()
		else:
			raise TypeError('Expected a concrete O type or NoneType')

		return result

	# Reject invalid external data before constructing persistent entities.
	# ----------------------------------------------------------------------
	def strict_validate(self, data_type, value):
		'''Validate external JSON against the existing O type schema without constructing an entity.'''
		json.dumps(value, allow_nan=False)
		schema = self.strict_schema(data_type)
		Draft202012Validator.check_schema(schema)
		Draft202012Validator(schema, registry=Registry()).validate(value)

	# Convert only validated JSON data into the declared ontology type.
	# ----------------------------------------------------------------------
	def strict_decode(self, data_type, value):
		'''Validate external data before conversion; return the declared type.'''
		self.strict_validate(data_type, value)
		result = None if data_type is type(None) else o.services.Entity.cast(data_type, value)

		self.strict_check(result, data_type)

		return result

	# Project actual typed data; never read or subscribe to a Resource.
	# ----------------------------------------------------------------------
	def strict_encode(self, data_type, value):
		'''Validate the actual typed value and its serialized representation.'''
		self.strict_check(value, data_type)
		result = None if data_type is type(None) else value.to_data()

		self.strict_validate(data_type, result)

		return result
