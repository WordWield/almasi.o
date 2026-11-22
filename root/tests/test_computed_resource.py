# ==============================================================================
# TEST COMPUTED RESOURCE
# ==============================================================================
# Verify stable cached values, reactive dependency scopes and resource lifetime.
# ==============================================================================

import gc
import weakref

from unittest import TestCase

from almasi import o
class TestComputedResource(o.Tester):
	RUNTIME_PREFIX = 'o_computed_resource_'

	# ==========================================================================
	# PUBLIC METHODS
	# ==========================================================================

	# Resource supplies Module identity through exactly one shared ancestor.
	# ----------------------------------------------------------------------
	@classmethod
	def test_resource_module_symmetry(cls):
		assert o.ComputedResource.__bases__ == (o.Resource,)
		assert o.Resource.__bases__ == (o.Module,)
		assert issubclass(o.ComputedResource, o.Module)

	# Keep a stable resource while filling and invalidating its value.
	# ----------------------------------------------------------------------
	@classmethod
	def test_observed_value_and_invalidation(cls):
		state = cls._patch_runtime()

		try:
			Model    = o.T.extend('ComputedObserved', count=int)
			item     = Model(count=4)
			resource = o.ComputedResource()
			events   = []
			handle   = resource.subscribe(events.append)

			assert resource.value is o.Undefined

			with o.services.Tracker.track_reads(resource) as observed:
				assert observed is resource
				observed.value = item.count * 2
				assert resource.read() is o.Undefined

			assert resource.read() == 8
			assert resource.dependencies == frozenset({item.id})
			assert handle._identifiers == frozenset({item.id})

			o.services.Sync._dispatch(frozenset({item.id}))

			assert resource.read() is o.Undefined
			assert events == [frozenset({item.id})]

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = item.count * 3

			assert resource.read() == 12
			handle.cancel()
		finally:
			cls._restore_runtime(state)

	# Preserve None as a valid cached value, not an absent result.
	# ----------------------------------------------------------------------
	@classmethod
	def test_null_result_and_empty_dependency_scope(cls):
		resource = o.ComputedResource()
		handle   = resource.subscribe(lambda changed: None)

		with o.services.Tracker.track_reads(resource) as observed:
			observed.value = None

		assert resource.read() is None
		assert resource.dependencies == frozenset()
		assert handle._identifiers == frozenset()
		handle.cancel()

	# Replace observation scope only after successful new computation.
	# ----------------------------------------------------------------------
	@classmethod
	def test_changing_dependencies(cls):
		state = cls._patch_runtime()

		try:
			Model    = o.T.extend('ComputedScopes', count=int)
			first    = Model(count=1)
			second   = Model(count=2)
			resource = o.ComputedResource()
			events   = []
			handle   = resource.subscribe(events.append)

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = first.count

			o.services.Sync._dispatch(frozenset({first.id}))
			assert resource.value is o.Undefined

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = second.count

			assert resource.dependencies == frozenset({second.id})
			assert handle._identifiers == frozenset({second.id})

			events.clear()
			o.services.Sync._dispatch(frozenset({first.id}))
			assert resource.read() == 2
			assert not events

			o.services.Sync._dispatch(frozenset({second.id}))
			assert resource.value is o.Undefined
			assert events == [frozenset({second.id})]
			handle.cancel()
		finally:
			cls._restore_runtime(state)

	# A newly encountered owner can invalidate a running computation.
	# ----------------------------------------------------------------------
	@classmethod
	def test_invalidation_during_with_rejects_value(cls):
		state = cls._patch_runtime()

		try:
			Model    = o.T.extend('ComputedConflict', count=int)
			item     = Model(count=1)
			resource = o.ComputedResource()
			handle   = resource.subscribe(lambda changed: None)

			with TestCase().assertRaisesRegex(RuntimeError, 'changed during read'):
				with o.services.Tracker.track_reads(resource) as observed:
					observed.value = item.count
					o.services.Sync.publish_change(frozenset({item.id}))

			assert resource.value is o.Undefined
			assert resource.dependencies == frozenset()
			assert handle._identifiers is None
			handle.cancel()
		finally:
			cls._restore_runtime(state)

	# A real committed write rejects the tracked result before worker delivery.
	# ----------------------------------------------------------------------
	@classmethod
	def test_committed_write_conflicts_without_worker_dispatch(cls):
		state = cls._patch_runtime()

		try:
			Model    = o.T.extend('ComputedCommittedConflict', count=int)
			item     = Model(count=1)
			resource = o.ComputedResource()
			handle   = resource.subscribe(lambda changed: None)

			with TestCase().assertRaisesRegex(RuntimeError, 'changed during read'):
				with o.services.Tracker.track_reads(resource) as observed:
					observed.value = item.count
					item.count = 2

			assert resource.value is o.Undefined
			assert resource.dependencies == frozenset()
			handle.cancel()
		finally:
			cls._restore_runtime(state)

	# A failed refresh retains existing source observation for recovery.
	# ----------------------------------------------------------------------
	@classmethod
	def test_failed_refresh_preserves_existing_subscription(cls):
		state = cls._patch_runtime()

		try:
			Model    = o.T.extend('ComputedFailure', count=int)
			first    = Model(count=1)
			second   = Model(count=2)
			resource = o.ComputedResource()
			handle   = resource.subscribe(lambda changed: None)

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = first.count

			o.services.Sync._dispatch(frozenset({first.id}))
			with TestCase().assertRaisesRegex(ValueError, 'intentional'):
				with o.services.Tracker.track_reads(resource) as observed:
					observed.value = second.count
					raise ValueError('intentional')

			assert resource.value is o.Undefined
			assert resource.dependencies == frozenset({first.id})
			assert handle._identifiers == frozenset({first.id})
			handle.cancel()
		finally:
			cls._restore_runtime(state)

	# Canceling the last source handle allows the resource to be collected.
	# ----------------------------------------------------------------------
	@classmethod
	def test_final_cancel_releases_resource(cls):
		def observed_reference():
			resource = o.ComputedResource()
			handle   = resource.subscribe(lambda changed: None)

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = 7

			assert resource.read() == 7
			reference = weakref.ref(resource)
			handle.cancel()
			return reference

		reference = observed_reference()
		gc.collect()

		assert reference() is None


if __name__ == '__main__':
	TestComputedResource.run()
