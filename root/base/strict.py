# ==============================================================================
# STRICT
# ==============================================================================
# PURPOSE:
# Extend checked Python calls with O's existing data representation.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Explicit typed data boundaries.
# Delegates: Method checks to Core, conversion and schema projection to O.
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

	# Describe data, including the declared contents of an observable carrier.
	# ----------------------------------------------------------------------
	@classmethod
	def __get_schema__(cls, annotation):
		data_type = cls._get_data_type(annotation)
		result    = {'type': 'null'} if data_type is type(None) else data_type.to_json_schema()

		return result

	# Check external data without constructing a persistent entity.
	# ----------------------------------------------------------------------
	def __validate__(self, annotation, value):
		json.dumps(value, allow_nan=False)
		schema = self.__get_schema__(annotation)
		Draft202012Validator.check_schema(schema)
		Draft202012Validator(schema, registry=Registry()).validate(value)

	# Validate before converting external data through the existing O cast.
	# ----------------------------------------------------------------------
	def __to_o__(self, data_type, value):
		if get_origin(data_type) is a.Resource:
			raise TypeError('Cannot construct a resource from data')

		self.__validate__(data_type, value)
		result = None if data_type is type(None) else o.services.Entity.cast(data_type, value)

		self._check_type(result, data_type)

		return result

	# Serialize actual data against its declared contract, without reading carriers.
	# ----------------------------------------------------------------------
	def __from_o__(self, annotation, value):
		data_type = self._get_data_type(annotation)

		self._check_type(value, data_type)
		result = None if data_type is type(None) else value.to_data()

		self.__validate__(data_type, result)

		return result

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Use the same data type for schema projection and result validation.
	# ----------------------------------------------------------------------
	@staticmethod
	def _get_data_type(annotation):
		if get_origin(annotation) is a.Resource:
			data_type, = get_args(annotation)

			if data_type is type(None):
				raise TypeError('Resource requires a concrete O content type')
		else:
			data_type = annotation

		is_data_type = isinstance(data_type, type) and data_type is not o.T and issubclass(data_type, o.T)

		if not is_data_type and data_type is not type(None):
			raise TypeError('Expected a concrete O type or NoneType')

		return data_type
