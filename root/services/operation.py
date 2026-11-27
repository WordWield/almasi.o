# ==============================================================================
# OPERATION SERVICE
# ==============================================================================
# PURPOSE:
# Bind and execute Python methods with O data contracts.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Typed signature interpretation, input binding and result validation.
# Delegates: Data schemas and conversion to O, carrier lifetime to Core.
# ==============================================================================

import inspect
import json
from typing import get_args, get_origin, get_type_hints

from jsonschema  import Draft202012Validator, ValidationError
from referencing import Registry

from almasi import a, o


class Operation(o.Singleton):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Accept only concrete ontology types.
	# ----------------------------------------------------------------------
	@staticmethod
	def _is_data_type(annotation):
		return isinstance(annotation, type) and annotation is not o.T and issubclass(annotation, o.T)

	# Validate the value directly, without a protocol-specific envelope.
	# ----------------------------------------------------------------------
	def _validate(self, data_type, value):
		json.dumps(value, allow_nan=False)
		schema = self.get_schema(data_type)
		Draft202012Validator.check_schema(schema)
		Draft202012Validator(schema, registry=Registry()).validate(value)

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Interpret the bound method's single input and optional trusted identity.
	# ----------------------------------------------------------------------
	def get_input(self, method):
		name         = None
		data_type    = None
		has_user_id  = False

		if inspect.ismethod(method) and inspect.iscoroutinefunction(method):
			hints = get_type_hints(method)

			for parameter in inspect.signature(method).parameters.values():
				if parameter.name == 'user_id':
					if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
						has_user_id = True
					else:
						raise TypeError('user_id must be keyword-only')
				else:
					annotation = hints.get(parameter.name)
					is_required = (
						name is None
						and parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
						and parameter.default is inspect.Parameter.empty
						and self._is_data_type(annotation)
					)

					if is_required:
						name      = parameter.name
						data_type = annotation
					else:
						raise TypeError('Expected zero or one required concrete O input')
		else:
			raise TypeError('Expected an asynchronous bound instance method')

		return name, data_type, has_user_id

	# Interpret the declared result independently of the consuming protocol.
	# ----------------------------------------------------------------------
	def get_output(self, method):
		annotation = get_type_hints(method).get('return', inspect.Signature.empty)
		is_carrier = get_origin(annotation) is a.Resource

		if is_carrier:
			arguments = get_args(annotation)

			if len(arguments) == 1 and self._is_data_type(arguments[0]):
				data_type = arguments[0]
			else:
				raise TypeError('Resource must declare one concrete O content type')
		elif self._is_data_type(annotation) or annotation is type(None):
			data_type = annotation
		else:
			raise TypeError('Expected a concrete O result, Resource[O type] or None')

		return data_type, is_carrier

	# Project a raw data schema; absence is distinct from a null result.
	# ----------------------------------------------------------------------
	def get_schema(self, data_type):
		if data_type is None:
			result = None
		elif data_type is type(None):
			result = {'type': 'null'}
		else:
			result = data_type.to_json_schema()

		return result

	# Validate input even when the caller reuses a previously resolved carrier.
	# ----------------------------------------------------------------------
	def validate_input(self, method, value=a.Undefined):
		_, data_type, _ = self.get_input(method)

		if data_type is None:
			if value is not a.Undefined:
				raise ValidationError('Operation does not accept a data input')
		elif value is not a.Undefined:
			self._validate(data_type, value)
		else:
			raise ValidationError('Operation requires a data input')

	# Invoke the actual bound method after validating its input.
	# ----------------------------------------------------------------------
	async def invoke(
		self,
		method,
		value   = a.Undefined,
		*,
		user_id = None
	):
		name, data_type, has_user_id = self.get_input(method)
		output_type, is_carrier      = self.get_output(method)

		self.validate_input(method, value)
		values = {}

		if name is not None:
			values[name] = o.services.Entity.cast(data_type, value)

		if has_user_id:
			values['user_id'] = user_id

		result        = await method(**values)
		expected_type = a.Resource if is_carrier else output_type

		if not isinstance(result, expected_type):
			raise TypeError('Operation returned a value outside its declared type')

		return result

	# Encode the actual data result, never consume or replace a carrier.
	# ----------------------------------------------------------------------
	def encode(self, method, value):
		data_type, _ = self.get_output(method)

		if isinstance(value, data_type):
			result = None if data_type is type(None) else value.to_data()
			self._validate(data_type, result)
		else:
			raise TypeError('Operation data does not match its declared type')

		return result
