# Copyright (c) 2022 Ole-Christoffer Granmo

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# This code implements the Convolutional Tsetlin Machine from paper arXiv:1905.09688
# https://arxiv.org/abs/1905.09688

from ._cb import ffi, lib

import numpy as np

import tmu.tools

class ClauseBank():
	def __init__(self, X, number_of_clauses, number_of_state_bits_ta, number_of_state_bits_ind, patch_dim):
		self.number_of_clauses = int(number_of_clauses)
		self.number_of_state_bits_ta = int(number_of_state_bits_ta)
		self.number_of_state_bits_ind = int(number_of_state_bits_ind)
		self.patch_dim = patch_dim

		if len(X.shape) == 2:
			self.dim = (X.shape[1], 1, 1)
		elif len(X.shape) == 3:
			self.dim = (X.shape[1], X.shape[2], 1)
		elif len(X.shape) == 4:
			self.dim = (X.shape[1], X.shape[2], X.shape[3])
		else:
			raise ValueError(f"Unsupported shape {X.shape}")

		if self.patch_dim == None:
			self.patch_dim = (self.dim[0]*self.dim[1]*self.dim[2], 1)

		self.number_of_features = int(self.patch_dim[0]*self.patch_dim[1]*self.dim[2] + (self.dim[0] - self.patch_dim[0]) + (self.dim[1] - self.patch_dim[1]))
		self.number_of_literals = self.number_of_features*2
		
		self.number_of_patches = int((self.dim[0] - self.patch_dim[0] + 1)*(self.dim[1] - self.patch_dim[1] + 1))
		self.number_of_ta_chunks = int((self.number_of_literals-1)/32 + 1)

		self.clause_output = np.ascontiguousarray(np.empty((int(self.number_of_clauses)), dtype=np.uint32))
		self.co_p = ffi.cast("unsigned int *", self.clause_output.ctypes.data)

		self.clause_and_target = np.ascontiguousarray(np.zeros((int(self.number_of_clauses*self.number_of_ta_chunks)), dtype=np.uint32))
		self.ct_p = ffi.cast("unsigned int *", self.clause_and_target.ctypes.data)

		self.clause_output_patchwise = np.ascontiguousarray(np.empty((int(self.number_of_clauses*self.number_of_patches)), dtype=np.uint32))
		self.cop_p = ffi.cast("unsigned int *", self.clause_output_patchwise.ctypes.data)

		self.feedback_to_ta = np.ascontiguousarray(np.empty((self.number_of_ta_chunks), dtype=np.uint32))
		self.ft_p = ffi.cast("unsigned int *", self.feedback_to_ta.ctypes.data)

		self.output_one_patches = np.ascontiguousarray(np.empty(self.number_of_patches, dtype=np.uint32))
		self.o1p_p = ffi.cast("unsigned int *", self.output_one_patches.ctypes.data)

		self.literal_clause_count = np.ascontiguousarray(np.empty((int(self.number_of_literals)), dtype=np.uint32))
		self.lcc_p = ffi.cast("unsigned int *", self.literal_clause_count.ctypes.data)

		self.initialize_clauses()

	def initialize_clauses(self):
		self.clause_bank = np.empty((self.number_of_clauses, self.number_of_ta_chunks, self.number_of_state_bits_ta), dtype=np.uint32)
		self.clause_bank[:,:,0:self.number_of_state_bits_ta-1] = np.uint32(~0)
		self.clause_bank[:,:,self.number_of_state_bits_ta-1] = 0
		self.clause_bank = np.ascontiguousarray(self.clause_bank.reshape((self.number_of_clauses * self.number_of_ta_chunks * self.number_of_state_bits_ta)))
		self.cb_p = ffi.cast("unsigned int *", self.clause_bank.ctypes.data)

		self.clause_bank_ind = np.empty((self.number_of_clauses, self.number_of_ta_chunks, self.number_of_state_bits_ind), dtype=np.uint32)
		self.clause_bank_ind[:,:,:] = np.uint32(~0)
		self.clause_bank_ind = np.ascontiguousarray(self.clause_bank_ind.reshape((self.number_of_clauses * self.number_of_ta_chunks * self.number_of_state_bits_ind)))
		self.cbi_p = ffi.cast("unsigned int *", self.clause_bank_ind.ctypes.data)

	def calculate_clause_outputs_predict(self, encoded_X, e):
		xi_p = ffi.cast("unsigned int *", encoded_X[e,:].ctypes.data)
		lib.cb_calculate_clause_outputs_predict(self.cb_p, self.number_of_clauses, self.number_of_literals, self.number_of_state_bits_ta, self.number_of_patches, self.co_p, xi_p)
		return self.clause_output

	def calculate_clause_outputs_update(self, literal_active, encoded_X, e):
		xi_p = ffi.cast("unsigned int *", encoded_X[e,:].ctypes.data)
		la_p = ffi.cast("unsigned int *", literal_active.ctypes.data)
		lib.cb_calculate_clause_outputs_update(self.cb_p, self.number_of_clauses, self.number_of_literals, self.number_of_state_bits_ta, self.number_of_patches, self.co_p, la_p, xi_p)
		return self.clause_output

	def calculate_clause_outputs_patchwise(self, encoded_X, e):
		xi_p = ffi.cast("unsigned int *", encoded_X[e,:].ctypes.data)
		lib.cb_calculate_clause_outputs_patchwise(self.cb_p, self.number_of_clauses, self.number_of_literals, self.number_of_state_bits_ta, self.number_of_patches, self.cop_p, xi_p)
		return self.clause_output_patchwise

	def type_i_feedback(self, update_p, s, boost_true_positive_feedback, max_included_literals, clause_active, literal_active, encoded_X, e):
		xi_p = ffi.cast("unsigned int *", encoded_X[e,:].ctypes.data)
		ca_p = ffi.cast("unsigned int *", clause_active.ctypes.data)
		la_p = ffi.cast("unsigned int *", literal_active.ctypes.data)
		lib.cb_type_i_feedback(self.cb_p, self.ft_p, self.o1p_p, self.number_of_clauses, self.number_of_literals, self.number_of_state_bits_ta, self.number_of_patches, update_p, s, boost_true_positive_feedback, max_included_literals, ca_p, la_p, xi_p)

	def type_ii_feedback(self, update_p, clause_active, literal_active, encoded_X, e):
		xi_p = ffi.cast("unsigned int *", encoded_X[e,:].ctypes.data)
		ca_p = ffi.cast("unsigned int *", clause_active.ctypes.data)
		la_p = ffi.cast("unsigned int *", literal_active.ctypes.data)
		lib.cb_type_ii_feedback(self.cb_p, self.o1p_p, self.number_of_clauses, self.number_of_literals, self.number_of_state_bits_ta, self.number_of_patches, update_p, ca_p, la_p, xi_p)

	def type_iii_feedback(self, update_p, d, clause_active, literal_active, encoded_X, e, target):
		xi_p = ffi.cast("unsigned int *", encoded_X[e,:].ctypes.data)
		ca_p = ffi.cast("unsigned int *", clause_active.ctypes.data)
		la_p = ffi.cast("unsigned int *", literal_active.ctypes.data)
		lib.cb_type_iii_feedback(self.cb_p, self.cbi_p, self.ct_p, self.o1p_p, self.number_of_clauses, self.number_of_literals, self.number_of_state_bits_ta, self.number_of_state_bits_ind, self.number_of_patches, update_p, d, ca_p, la_p, xi_p, target)

	def calculate_literal_clause_frequency(self, clause_active):
		ca_p = ffi.cast("unsigned int *", clause_active.ctypes.data)
		lib.cb_calculate_literal_frequency(self.cb_p, self.number_of_clauses, self.number_of_literals, self.number_of_state_bits_ta, ca_p, self.lcc_p)
		return self.literal_clause_count
	
	def number_of_include_actions(self, clause):
		return lib.cb_number_of_include_actions(self.cb_p, clause, self.number_of_literals, self.number_of_state_bits_ta)

	def get_ta_action(self, clause, ta):
		ta_chunk = ta // 32
		chunk_pos = ta % 32
		pos = int(clause * self.number_of_ta_chunks * self.number_of_state_bits_ta + ta_chunk * self.number_of_state_bits_ta + self.number_of_state_bits_ta-1)
		return (self.clause_bank[pos] & (1 << chunk_pos)) > 0

	def get_ta_state(self, clause, ta):
		ta_chunk = ta // 32
		chunk_pos = ta % 32
		pos = int(clause * self.number_of_ta_chunks * self.number_of_state_bits_ta + ta_chunk * self.number_of_state_bits_ta)
		state = 0
		for b in range(self.number_of_state_bits_ta):
			if self.clause_bank[pos + b] & (1 << chunk_pos) > 0:
				state |= (1 << b)
		return state

	def set_ta_state(self, clause, ta, state):
		ta_chunk = ta // 32
		chunk_pos = ta % 32
		pos = int(clause * self.number_of_ta_chunks * self.number_of_state_bits_ta + ta_chunk * self.number_of_state_bits_ta)
		for b in range(self.number_of_state_bits_ta):
			if state & (1 << b) > 0:
				self.clause_bank[pos + b] |= (1 << chunk_pos)
			else:
				self.clause_bank[pos + b] &= ~(1 << chunk_pos)

	def prepare_X(self, X):		
		return tmu.tools.encode(X, X.shape[0], self.number_of_patches, self.number_of_ta_chunks, self.dim, self.patch_dim, 0)
