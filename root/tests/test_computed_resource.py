# ==============================================================================
# TEST COMPUTED RESOURCE
# ==============================================================================
# Verify resource value caching, source subscriptions and collection.
# ==============================================================================

import gc
import weakref

import o


class TestComputedResource(o.Tester):

	# ==========================================================================
	# PUBLIC METHODS
	# ==========================================================================

	# Preserve one resource identity while replacing observed dependencies.
	# ----------------------------------------------------------------------
	@classmethod
	def test_cached_value_and_reindex(cls):
		sync     = o.services.Sync
		resource = o.ComputedResource('computed-resource-test')
		events   = []
		first    = resource.subscribe(events.append)
		second   = resource.subscribe(events.append)

		try:
			assert resource.id == 'computed-resource-test'
			assert resource.read() is o.Undefined
			assert first is not second
			assert first._identifiers is None

			resource.replace(None, {710001})
			assert resource.read() is None
			assert resource.dependencies == frozenset({710001})
			assert first._identifiers == frozenset({710001})
			assert second._identifiers == frozenset({710001})

			sync._dispatch(frozenset({710002}))
			assert events == []
			assert resource.read() is None

			sync._dispatch(frozenset({710001}))
			assert events == [frozenset({710001}), frozenset({710001})]
			assert resource.read() is o.Undefined
			assert resource.dependencies == frozenset({710001})

			resource.replace(42, {710002})
			assert resource.read() == 42
			assert resource.dependencies == frozenset({710002})

			sync._dispatch(frozenset({710001}))
			assert len(events) == 2
			sync._dispatch(frozenset({710002}))
			assert len(events) == 4
			assert resource.read() is o.Undefined
		finally:
			first.cancel()
			second.cancel()

	# Keep the previous dependency watch if a replacement cannot complete.
	# ----------------------------------------------------------------------
	@classmethod
	def test_failed_reindex_keeps_old_dependencies(cls):
		resource = o.ComputedResource('computed-resource-failure')
		first    = resource.subscribe(lambda changes: None)
		second   = resource.subscribe(lambda changes: None)

		try:
			resource.replace('before', {720001})
			second.cancel()

			# Canceled registrations are ignored; active ones can still update.
			# --------------------------------------------------------------
			resource.replace('after', {720002})
			assert resource.read() == 'after'
			assert first._identifiers == frozenset({720002})
		finally:
			first.cancel()
			second.cancel()

	# Unused resources disappear after the last listener is canceled.
	# ----------------------------------------------------------------------
	@classmethod
	def test_collect_after_last_cancel(cls):
		resource = o.ComputedResource('computed-resource-gc')
		ref      = weakref.ref(resource)
		handle   = resource.subscribe(lambda changed: None)

		assert ref() is resource
		handle.cancel()
		del resource
		del handle
		gc.collect()

		assert ref() is None

	# The existing Tracker can observe a computation without replaying its body.
	# ----------------------------------------------------------------------
	@classmethod
	def test_existing_tracker_scope(cls):
		resource = o.ComputedResource('computed-resource-tracking')
		reads    = []

		with o.services.Tracker.track_reads(reads):
			value = 17

		resource.replace(value, reads)

		assert resource.read() == 17
		assert resource.dependencies == frozenset()


if __name__ == '__main__':
	TestComputedResource.run()
