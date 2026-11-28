# ==============================================================================
# STRICT
# ==============================================================================
# PURPOSE:
# Extend checked Python methods with a fixed JSON contract for O values.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Schema preparation and validation of external values.
# Delegates: Method contracts to Core, schemas and conversion to O.
# ==============================================================================

import json

from jsonschema  import Draft202012Validator
from referencing import Registry

from almasi import a, o


class Strict(a.base.Strict):

	# ======================================================================
	# FRAMEWORK METHODS
	# ======================================================================

	# Validate JSON against the schema prepared for the declared value.
	# ----------------------------------------------------------------------
	def __validate__(self, field, value):
		json.dumps(value, allow_nan=False)
		Draft202012Validator(field['jsonschema'], registry=Registry()).validate(value)

		return value

	# Validate external data before constructing an O entity.
	# ----------------------------------------------------------------------
	def __to_o__(self, field, value):
		data_type = field['type']
		value     = self.__validate__(field, value)
		result    = o.services.Entity.cast(data_type, value)

		return self._check_type(result, data_type)

	# Serialize a checked result and validate its external representation.
	# ----------------------------------------------------------------------
	def __from_o__(self, field, value):
		value = self._check_type(value, field['type'])
		data  = None if value is None else value.to_data()

		return self.__validate__(field, data)

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Prepare the JSON contract before publishing the checked method.
	# ----------------------------------------------------------------------
	@classmethod
	def _decorate_method(cls, method, signature):
		for field in signature['inputs'].values():
			cls._prepare_schema(field)

		output = signature['output']

		if output['type'] is type(None):
			output['jsonschema'] = {'type': 'null'}
		else:
			cls._prepare_schema(output)

		return super()._decorate_method(method, signature)

	# Derive and check the schema of a concrete O type once.
	# ----------------------------------------------------------------------
	@staticmethod
	def _prepare_schema(field):
		data_type    = field['type']
		is_data_type = isinstance(data_type, type) and issubclass(data_type, o.T) and data_type is not o.T

		if is_data_type:
			schema = data_type.to_json_schema()
			Draft202012Validator.check_schema(schema)
			field['jsonschema'] = schema
		else:
			raise TypeError(f'Expected a concrete O type, got {data_type!r}')
