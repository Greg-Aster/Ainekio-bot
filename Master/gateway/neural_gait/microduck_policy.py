"""Bounded foot-action distribution for the imported RSL-RL actor/exporter."""
import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from rsl_rl.modules.distribution import GaussianDistribution


class FootGaussianDistribution(GaussianDistribution):
    """Tanh Gaussian with transformed likelihood, entropy and export.

    KL is invariant under this invertible transform, so RSL's existing Gaussian
    KL adaptation remains valid using the latent Normal parameters. Entropy is
    computed in the bounded action domain using Gauss-Hermite quadrature;
    increasing latent variance cannot earn unbounded entropy reward.
    """
    def __init__(self, output_dim, init_std=1., std_type="log"):
        super().__init__(output_dim, init_std, std_type)
        nodes, weights = np.polynomial.hermite.hermgauss(16)
        self.register_buffer("nodes", torch.tensor(nodes, dtype=torch.float32))
        self.register_buffer("weights", torch.tensor(weights/math.sqrt(math.pi), dtype=torch.float32))

    def sample(self):
        return self._distribution.sample().tanh()

    def deterministic_output(self, mlp_output):
        return mlp_output.tanh()

    def as_deterministic_output_module(self):
        return nn.Tanh()

    @property
    def mean(self):
        return self._distribution.mean.tanh()

    @property
    def params(self):
        return self._distribution.mean, self._distribution.stddev

    def _quadrature(self):
        return (self._distribution.mean[..., None] + math.sqrt(2)*
                self._distribution.stddev[..., None]*self.nodes)

    @property
    def std(self):
        values=self._quadrature().tanh()
        mean=(values*self.weights).sum(-1)
        return ((values.square()*self.weights).sum(-1)-mean.square()).clamp_min(0).sqrt()

    @property
    def entropy(self):
        latent=self._quadrature()
        log_jacobian=2*(math.log(2)-latent-F.softplus(-2*latent))
        return (self._distribution.entropy()+(log_jacobian*self.weights).sum(-1)).sum(-1)

    def log_prob(self, outputs):
        # Only avoid atanh(+-1) at the floating-point endpoint; the physical
        # action contract retains its complete [-1, 1] range.
        epsilon=torch.finfo(outputs.dtype).eps
        action=outputs.clamp(-1+epsilon,1-epsilon)
        latent=torch.atanh(action)
        log_jacobian=2*(math.log(2)-latent-F.softplus(-2*latent))
        return (self._distribution.log_prob(latent)-log_jacobian).sum(-1)
