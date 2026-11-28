# ==============================================================================
# STRICT
# ==============================================================================
# PURPOSE:
# Extend automatic Python method checks with explicit O data conversion.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Validation of external data against concrete O declarations.
# Delegates: Python method contracts to Core and conversion to O.
# ==============================================================================

import json
from typing import get_args, get_origin

from jsonschema  import Draft202012Validator
from referencing import Registry

from almasi import a, o


class Strict(a.base.Strict):

	# ======================================================================
	# FRAMEWORK METHODS
	# ======================================================================

	# Describe data, including the declared contents of a resource.
	# ----------------------------------------------------------------------
	@classmethod
	def __get_schema__(cls, annotation):
		data_type = cls._get_data_type(annotation)

		return {'type': 'null'} if data_type is type(None) else data_type.to_json_schema()

	# Return validated external data without constructing an O entity.
	# ----------------------------------------------------------------------
	def __validate__(self, annotation, value):
		json.dumps(value, allow_nan=False)
		schema = self.__get_schema__(annotation)
		Draft202012Validator.check_schema(schema)
		Draft202012Validator(schema, registry=Registry()).validate(value)

		return value

	# Validate external data before constructing an O entity.
	# ----------------------------------------------------------------------
	def __to_o__(self, data_type, value):
		if get_origin(data_type) is not a.Resource:
			value  = self.__validate__(data_type, value)
			result = None if data_type is type(None) else o.services.Entity.cast(data_type, value)
		else:
			raise TypeError('Cannot construct a resource from data')

		return self._check_type(result, data_type)

	# Validate actual O content before serializing it.
	# ----------------------------------------------------------------------
	def __from_o__(self, annotation, value):
		data_type = self._get_data_type(annotation)
		value     = self._check_type(value, data_type)
		result    = None if data_type is type(None) else value.to_data()

		return self.__validate__(data_type, result)

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Resolve a concrete data type without reading a resource carrier.
	# ----------------------------------------------------------------------
	@staticmethod
	def _get_data_type(annotation):
		is_resource = get_origin(annotation) is a.Resource
		data_type   = get_args(annotation)[0] if is_resource else annotation

		is_data_type = isinstance(data_type, type) and data_type is not o.T and issubclass(data_type, o.T)
		is_null      = not is_resource and data_type is type(None)

		if is_data_type or is_null:
			result = data_type
		else:
			raise TypeError('Expected a concrete O type or NoneType outside a resource')

		return result
