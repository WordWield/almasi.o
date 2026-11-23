# ==============================================================================
# GARBAGE SERVICE
# ==============================================================================
# Track references and collect unreachable persistent entities.
# ==============================================================================

from almasi import o
class Garbage(o.Singleton):

	# Initialize service
	# ----------------------------------------------------------------------
	def initialize(self):
		memory = o.services.Memory

		self.refcounts = memory.zone('garbage/refcounts/')
		self.garbage   = memory.zone('garbage/items/')

		self.collect()

	# Mark new instances collectable until retained through the root.
	# ----------------------------------------------------------------------
	def on_instance_create(self, cls, id, proto):
		if cls is not o.T.V:
			self.garbage.set(id, proto, id)

	# An edge retains its child only while its owner is retained.
	# ----------------------------------------------------------------------
	def _is_retained(self, owner):
		result = (
			owner is None
			or isinstance(owner, o.T.V)
			or self.refcounts.get(owner.id, 0) > 0
		)
		return result

	# Link a holding edge whose owner is retained.
	# ----------------------------------------------------------------------
	def on_instance_link(self, instance, owner=None):
		if self._is_retained(owner):
			with o.services.Memory.write():
				self._on_instance_link(instance)

	# Link holding edge in active transaction
	# ----------------------------------------------------------------------
	def _on_instance_link(self, instance):
		old_count = self.refcounts.get(instance.id, 0)
		count     = old_count + 1

		self.refcounts.set(instance.id, count, instance.id)
		self.garbage.unset(instance.id, instance.id)

		if old_count == 0:
			for child in instance.__holding_children__():
				self._on_instance_link(child)

	# Unlink a holding edge whose owner was retained.
	# ----------------------------------------------------------------------
	def on_instance_unlink(self, instance, owner=None):
		if self._is_retained(owner):
			with o.services.Memory.write():
				self._on_instance_unlink(instance)

	# Unlink holding edge in active transaction
	# ----------------------------------------------------------------------
	def _on_instance_unlink(self, instance):
		old_count = self.refcounts.get(instance.id, 0)
		count     = max(old_count - 1, 0)

		if count == 0:
			self.refcounts.unset(instance.id, instance.id)
			self.garbage.set(instance.id, instance.__proto__, instance.id)

			if old_count == 1:
				for child in instance.__holding_children__():
					self._on_instance_unlink(child)
		else:
			self.refcounts.set(instance.id, count, instance.id)

	# Collect garbage storage
	# ----------------------------------------------------------------------
	def collect(self):
		with o.services.Memory.write():
			for id, proto in self.garbage.items():
				if o.TREE_MODE:
					o.services.Memory.unset(f'tree/parents/{id}', int(id))

				owner_id = (int(id), o.services.Id.hash(proto.rsplit('.', 1)[0]))
				o.services.Memory.unset(proto, owner_id)
				o.services.Memory.zone(f'{proto}.').clear()
				o.services.Id.unset(int(id))

			self.clear()

	# Clear garbage storage
	# ----------------------------------------------------------------------
	def clear(self):
		self.garbage.clear(int(id) for id in self.garbage.keys())
