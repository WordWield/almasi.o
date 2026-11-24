# ==============================================================================
# TEST COMPUTED RESOURCE
# ==============================================================================
# PURPOSE:
# Verify stable cached values, observed dependency scopes and resource lifetime.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Assertions about shared observation and computed value invalidation.
# Delegates: Registration and delivery to Resource and O Sync.
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
		assert o.resources.Computed.__bases__ == (o.Resource,)
		assert o.Resource.__bases__ == (o.Module,)
		assert issubclass(o.resources.Computed, o.Module)

	# Keep a stable resource while filling and invalidating its value.
	# ----------------------------------------------------------------------
	@classmethod
	def test_observed_value_and_invalidation(cls):
		state = cls._patch_runtime()

		try:
			Model    = o.T.extend('ComputedObserved', count=int)
			item     = Model(count=4)
			resource = o.resources.Computed()
			events   = []
			handle   = resource.subscribe(events.append)

			assert resource.value is o.Undefined

			with o.services.Tracker.track_reads(resource) as observed:
				assert observed is resource
				observed.value = item.count * 2
				assert resource.read() is o.Undefined

			assert resource.read() == 8
			assert o.resources.Computed.subscribe is o.Resource.subscribe

			second_events = []
			second_handle = resource.subscribe(second_events.append)
			assert o.services.Sync._by_id[item.id] == {resource}
			assert resource.dependencies == frozenset({item.id})
			assert o.services.Sync._resources[resource][2] == frozenset({item.id})

			o.services.Sync._dispatch(frozenset({item.id}))

			assert resource.read() is o.Undefined
			assert events == [frozenset({item.id})]
			assert second_events == events
			resource.unsubscribe(second_handle)
			assert resource in o.services.Sync._resources

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = item.count * 3

			assert resource.read() == 12
			resource.unsubscribe(handle)
			assert resource not in o.services.Sync._resources
		finally:
			cls._restore_runtime(state)

	# Preserve None as a valid cached value, not an absent result.
	# ----------------------------------------------------------------------
	@classmethod
	def test_null_result_and_empty_dependency_scope(cls):
		resource = o.resources.Computed()
		handle   = resource.subscribe(lambda changed: None)

		with o.services.Tracker.track_reads(resource) as observed:
			observed.value = None

		assert resource.read() is None
		assert resource.dependencies == frozenset()
		assert o.services.Sync._resources[resource][2] == frozenset()
		resource.unsubscribe(handle)

	# An unchanged dependency scope must preserve the dispatch snapshot and index.
	# ----------------------------------------------------------------------
	@classmethod
	def test_unchanged_dependencies_preserve_index(cls):
		resource = o.resources.Computed()
		handle   = resource.subscribe(lambda changed: None)
		sync     = o.services.Sync

		try:
			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = 1

			snapshot = sync._snapshot
			entry    = sync._resources[resource]

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = 2

			assert resource.read() == 2
			assert sync._snapshot is snapshot
			assert sync._resources[resource] is entry
		finally:
			resource.unsubscribe(handle)

	# Replace observation scope only after successful new computation.
	# ----------------------------------------------------------------------
	@classmethod
	def test_changing_dependencies(cls):
		state = cls._patch_runtime()

		try:
			Model    = o.T.extend('ComputedScopes', count=int)
			first    = Model(count=1)
			second   = Model(count=2)
			resource = o.resources.Computed()
			events   = []
			handle   = resource.subscribe(events.append)

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = first.count

			o.services.Sync._dispatch(frozenset({first.id}))
			assert resource.value is o.Undefined

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = second.count

			assert resource.dependencies == frozenset({second.id})
			assert o.services.Sync._resources[resource][2] == frozenset({second.id})

			events.clear()
			o.services.Sync._dispatch(frozenset({first.id}))
			assert resource.read() == 2
			assert not events

			o.services.Sync._dispatch(frozenset({second.id}))
			assert resource.value is o.Undefined
			assert events == [frozenset({second.id})]
			resource.unsubscribe(handle)
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
			resource = o.resources.Computed()
			handle   = resource.subscribe(lambda changed: None)

			with TestCase().assertRaisesRegex(RuntimeError, 'changed during read'):
				with o.services.Tracker.track_reads(resource) as observed:
					observed.value = item.count
					o.services.Sync.publish_change(frozenset({item.id}))

			assert resource.value is o.Undefined
			assert resource.dependencies == frozenset()
			assert o.services.Sync._resources[resource][2] is None
			resource.unsubscribe(handle)
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
			resource = o.resources.Computed()
			handle   = resource.subscribe(lambda changed: None)

			with TestCase().assertRaisesRegex(RuntimeError, 'changed during read'):
				with o.services.Tracker.track_reads(resource) as observed:
					observed.value = item.count
					item.count = 2

			assert resource.value is o.Undefined
			assert resource.dependencies == frozenset()
			resource.unsubscribe(handle)
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
			resource = o.resources.Computed()
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
			assert o.services.Sync._resources[resource][2] == frozenset({first.id})
			resource.unsubscribe(handle)
		finally:
			cls._restore_runtime(state)

	# Canceling the last source handle allows the resource to be collected.
	# ----------------------------------------------------------------------
	@classmethod
	def test_final_cancel_releases_resource(cls):
		def observed_reference():
			resource = o.resources.Computed()
			handle   = resource.subscribe(lambda changed: None)

			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = 7

			assert resource.read() == 7
			reference = weakref.ref(resource)
			resource.unsubscribe(handle)
			return reference

		reference = observed_reference()
		gc.collect()

		assert reference() is None


if __name__ == '__main__':
	TestComputedResource.run()
