# ==============================================================================
# TEST CAST
# ==============================================================================
# Verify conversions between Python values and ontology entities.
# ==============================================================================

import os
from unittest.mock import patch

from jsonschema import ValidationError

from almasi import a, o
class TestCast(o.Tester):
	RUNTIME_PREFIX = 'o_cast_'

	# ----------------------------------------------------------------------
	@classmethod
	def test_object_field_casts_raw_dict_into_declared_class(cls):
		state = cls._patch_runtime()

		try:
			root_name = os.path.basename(state['root'])
			Child     = o.T.extend(f'CastObjectFieldChild_{root_name}', name=str)
			Parent    = o.T.extend(f'CastObjectFieldParent_{root_name}', child=Child)
			parent    = Parent(child={'name': 'alex'})

			assert isinstance(parent.child, Child)
			assert parent.child.name == 'alex'
		finally:
			cls._restore_runtime(state)

	# ----------------------------------------------------------------------
	@classmethod
	def test_object_field_recasts_generic_dict_into_declared_class(cls):
		state = cls._patch_runtime()

		try:
			root_name = os.path.basename(state['root'])
			Child     = o.T.extend(f'CastGenericObjectFieldChild_{root_name}', name=str)
			Parent    = o.T.extend(f'CastGenericObjectFieldParent_{root_name}', child=Child)
			parent    = Parent(child=o.Dict({'name': 'alex'}))

			assert isinstance(parent.child, Child)
			assert parent.child.name == 'alex'
		finally:
			cls._restore_runtime(state)

	# ----------------------------------------------------------------------
	@classmethod
	def test_object_field_casts_list_items_into_declared_class(cls):
		state = cls._patch_runtime()

		try:
			root_name = os.path.basename(state['root'])
			Child     = o.T.extend(f'CastListFieldChild_{root_name}', name=str)
			Parent    = o.T.extend(f'CastListFieldParent_{root_name}', children=o.F(list[Child]))
			parent    = Parent(children=[{'name': 'alex'}, {'name': 'bob'}])

			assert isinstance(parent.children[0], Child)
			assert parent.children[0].name == 'alex'
			assert isinstance(parent.children[1], Child)
			assert parent.children[1].name == 'bob'
		finally:
			cls._restore_runtime(state)

	# ----------------------------------------------------------------------
	@classmethod
	def test_typed_list_recasts_generic_input_and_mutations(cls):
		state = cls._patch_runtime()

		try:
			root_name     = os.path.basename(state['root'])
			Child         = o.T.extend(f'CastTypedListChild_{root_name}', name=str)
			TypedChildren = o.T.extend(f'CastTypedList_{root_name}', list[Child])
			x             = TypedChildren(o.List([{'name': 'alex'}]))

			x.append({'name': 'bob'})
			x[0] = {'name': 'aria'}

			assert isinstance(x[0], Child)
			assert x[0].name == 'aria'
			assert isinstance(x[1], Child)
			assert x[1].name == 'bob'
		finally:
			cls._restore_runtime(state)

	# ----------------------------------------------------------------------
	@classmethod
	def test_object_field_casts_typed_dict_keys_and_values(cls):
		state = cls._patch_runtime()

		try:
			root_name = os.path.basename(state['root'])
			Child     = o.T.extend(f'CastDictFieldChild_{root_name}', name=str)
			Parent    = o.T.extend(f'CastDictFieldParent_{root_name}', children=o.F(dict[str, Child]))
			parent    = Parent(children={1: {'name': 'alex'}, 2: {'name': 'bob'}})
			items     = dict(parent.children.items())

			assert '1' in items
			assert items['1'].name == 'alex'
			assert '2' in items
			assert items['2'].name == 'bob'
			assert isinstance(items['1'], Child)
			assert isinstance(items['2'], Child)
		finally:
			cls._restore_runtime(state)

	# ----------------------------------------------------------------------
	@classmethod
	def test_typed_dict_recasts_generic_input_and_mutations(cls):
		state = cls._patch_runtime()

		try:
			root_name     = os.path.basename(state['root'])
			Child         = o.T.extend(f'CastTypedDictChild_{root_name}', name=str)
			TypedChildren = o.T.extend(f'CastTypedDict_{root_name}', dict[str, Child])
			x             = TypedChildren(o.Dict({1: {'name': 'alex'}}))

			x[2] = {'name': 'bob'}
			x.update({3: {'name': 'aria'}})

			items = dict(x.items())

			assert '1' in items
			assert items['1'].name == 'alex'
			assert '2' in items
			assert items['2'].name == 'bob'
			assert '3' in items
			assert items['3'].name == 'aria'
			assert isinstance(items['1'], Child)
			assert isinstance(items['2'], Child)
			assert isinstance(items['3'], Child)
		finally:
			cls._restore_runtime(state)

	# Keep nested entities intact in shallow representations.
	# ----------------------------------------------------------------------
	@classmethod
	def test_shallow_data_preserves_nested_types(cls):
		state = cls._patch_runtime()
		try:
			root_name = os.path.basename(state['root'])
			Base = o.T.extend(f'ShallowBase_{root_name}', label=str)
			Derived = Base.extend('Derived', conclusion=str)
			Parent = o.T.extend(f'ShallowParent_{root_name}', child=Base)
			child = Derived(label='seen', conclusion='learned')
			parent = Parent(child=child)

			assert parent.to_data_shallow()['child'].id == child.id
			assert o.Dict({'alex': child}).to_data_shallow()['alex'].id == child.id
			assert o.List([child]).to_data_shallow()[0].id == child.id
			assert o.Str('hello').to_data_shallow() == 'hello'
		finally:
			cls._restore_runtime(state)

	# Preserve nested subclasses across typed collection and object casts.
	# ----------------------------------------------------------------------
	@classmethod
	def test_cast_preserves_nested_subclasses(cls):
		state = cls._patch_runtime()
		try:
			root_name = os.path.basename(state['root'])
			Base = o.T.extend(f'CastBase_{root_name}', label=str)
			Derived = Base.extend('Derived', conclusion=str)
			Source = o.T.extend(f'CastSource_{root_name}', child=Base)
			Target = o.T.extend(f'CastTarget_{root_name}', child=Base)
			Holder = o.T.extend(
				f'CastHolder_{root_name}',
				reactions=dict[str, Base],
				entries=list[Base],
			)
			child = Derived(label='seen', conclusion='learned')
			holder = Holder(
				reactions=o.Dict({'alex': child}),
				entries=o.List([child]),
			)
			converted = o.services.Entity.cast(Target, Source(child=child))

			assert isinstance(holder.reactions['alex'], Derived)
			assert isinstance(holder.entries[0], Derived)
			assert holder.reactions['alex'].id == child.id
			assert holder.entries[0].id == child.id
			assert isinstance(converted.child, Derived)
			assert converted.child.id == child.id
		finally:
			cls._restore_runtime(state)


	# Verify class-load schemas and their reuse throughout the data boundary.
	# ----------------------------------------------------------------------
	@classmethod
	def test_strict_data_boundary(cls):
		state = cls._patch_runtime()

		try:
			with patch.object(o.JsonSchema, 'build', wraps=o.JsonSchema.build) as build:
				class Example(o.base.Strict):

					def increment(self, value: o.Int) -> o.Int:
						return o.Int(value.to_data() + 1)

					def command(self) -> None:
						return None

					def null(self, value: o.Null) -> o.Null:
						return value

				class Child(Example):
					'''Reuse inherited method contracts.'''

				assert build.call_count == 4

				example   = Child()
				signature = example.increment.__signature__
				input     = signature['inputs']['value']
				output    = signature['output']

				assert issubclass(o.base.Strict, a.base.Strict)
				assert Child.increment.__signature__ is Example.increment.__signature__
				assert input == {'type': o.Int, 'jsonschema': {'type': 'integer'}}
				assert output == input

				value = example.__to_o__(input, 3)
				assert isinstance(value, o.Int)
				assert example.__from_o__(output, example.increment(value)) == 4

				command = example.command.__signature__['output']
				assert command == {'type': type(None), 'jsonschema': {'type': 'null'}}
				assert example.__from_o__(command, example.command()) is None

				null_signature = example.null.__signature__
				null_value     = example.__to_o__(null_signature['inputs']['value'], None)
				assert isinstance(null_value, o.Null)
				assert example.__from_o__(null_signature['output'], example.null(null_value)) is None

				for invalid in ('3', True, None):
					try:
						example.__to_o__(input, invalid)
					except ValidationError:
						pass
					else:
						assert False, 'Invalid JSON was converted to an O entity'

				try:
					example.increment(3)
				except TypeError:
					pass
				else:
					assert False, 'Strict Python invocation coerced an input'

				assert build.call_count == 4
		finally:
			cls._restore_runtime(state)

	# Reject non-O declarations at class definition, including None inputs.
	# ----------------------------------------------------------------------
	@classmethod
	def test_strict_declarations(cls):
		state = cls._patch_runtime()

		try:
			for source in (
				'def call(self, value: int) -> o.Int: return value',
				'def call(self, value: None) -> o.Int: return value',
				'def call(self, value: o.T) -> o.Int: return value',
				'def call(self) -> str: return ""',
				'def call(self) -> a.Resource[o.Int]: return None',
				'def call(self, value): return value',
			):
				try:
					exec('class Invalid(o.base.Strict):\n\t' + source, {'a': a, 'o': o})
				except TypeError:
					pass
				else:
					assert False, 'Invalid O method declaration was accepted'
		finally:
			cls._restore_runtime(state)


if __name__ == '__main__':
	TestCast.run()
