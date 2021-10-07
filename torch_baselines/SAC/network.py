import numpy as np
import jax.numpy as jnp
from torch_baselines.common.utils import get_flatten_size
from torch_baselines.common.layer import NoisyLinear
import torch
import torch.nn as nn
import torch.nn.functional as F

EPS = 1e-6  # Avoid NaN (prevents division by zero or log of zero)
# CAP the standard deviation of the actor
LOG_STD_MAX = 2
LOG_STD_MIN = -20
log_2pi = np.log(2.0 * np.pi)
log_2pie_div2 = 0.5 * np.log(2.0 * np.pi * np.e)

def gaussian_likelihood(input_, mu_, log_std):
    pre_sum = -0.5 * (((input_ - mu_) / (torch.exp(log_std) + EPS)) ** 2 + 2 * log_std + log_2pi)
    #pre_sum = -0.5 * (((input_ - mu_) / (torch.exp(log_std) + EPS)) ** 2 + 2 * log_std + np.log(2 * np.pi))
    return pre_sum.sum(axis=1)


def gaussian_entropy(log_std):
    return (log_std + log_2pie_div2).sum(-1)
    #return (log_std + 0.5 * np.log(2.0 * np.pi * np.e)).sum(-1)


def clip_but_pass_gradient(input_, lower=-1., upper=1.):
    with torch.no_grad():
        clip_up = (input_ > upper).float()
        clip_low = (input_ < lower).float()
        sub = (upper - input_) * clip_up + (lower - input_) * clip_low
    return input_ + sub

class Actor(nn.Module):
    def __init__(self,state_size,action_size,node=256,noisy=False,ModelOptions=None):
        super(Actor, self).__init__()
        self.noisy = noisy
        if noisy:
            lin = NoisyLinear
        else:
            lin = nn.Linear
        self.preprocess = nn.ModuleList([
            nn.Sequential(
                nn.Conv2d(st[0],16,kernel_size=4, stride=2, padding=0),
                nn.ReLU(),
                nn.Conv2d(16,32,kernel_size=3,stride=1),
                nn.ReLU(),
                nn.Flatten()
            )
            if len(st) == 3 else nn.Identity()
            for st in state_size 
        ])
        
        flatten_size = np.sum(
                       np.asarray(
                        [
                        get_flatten_size(pr,st)
                        for pr,st in zip(self.preprocess,state_size)
                        ]
                        ))
        
        self.linear = nn.Sequential(
            lin(flatten_size,node),
            nn.ReLU(),
            lin(node,node),
            nn.ReLU(),
        )
        self.act_mu  = lin(node, action_size[0])
        self.log_std = lin(node, action_size[0])

    def forward(self, xs):
        flats = [pre(x) for pre,x in zip(self.preprocess,xs)]
        cated = torch.cat(flats,dim=-1)
        lin = self.linear(cated)
        mu = self.act_mu(lin)
        log_std = torch.clip(self.log_std(lin),LOG_STD_MIN,LOG_STD_MAX)
        std = torch.exp(log_std)
        pi = torch.normal(mu,std,device=self.linear.device)
        return F.tanh(pi)
        
    def sample_noise(self):
        if not self.noisy:
            return
        for m in self.modules():
            if isinstance(m,NoisyLinear):
                m.sample_noise()
                
    def update_data(self, xs):
        flats = [pre(x) for pre,x in zip(self.preprocess,xs)]
        cated = torch.cat(flats,dim=-1)
        lin = self.linear(cated)
        mu = self.act_mu(lin)
        log_std = torch.clip(self.log_std(lin),LOG_STD_MIN,LOG_STD_MAX)
        std = torch.exp(log_std)
        pi = torch.normal(mu,std,device=self.linear.device)
        logp_pi = gaussian_likelihood(pi, mu, log_std)
        entropy = gaussian_entropy(log_std)
        deterministic_policy = F.tanh(mu)
        policy = F.tanh(pi)
        logp_pi -= torch.log(1-policy**2 + EPS).sum(1)
        return deterministic_policy, policy, logp_pi, entropy
    

class Critic(nn.Module):
    def __init__(self,state_size,action_size,node=256,noisy=False,ModelOptions=None):
        super(Critic, self).__init__()
        self.noisy = noisy
        if noisy:
            lin = NoisyLinear
        else:
            lin = nn.Linear
        self.preprocess = nn.ModuleList([
            nn.Sequential(
                nn.Conv2d(st[0],16,kernel_size=4, stride=2, padding=0),
                nn.ReLU(),
                nn.Conv2d(16,32,kernel_size=3,stride=1),
                nn.ReLU(),
                nn.Flatten()
            )
            if len(st) == 3 else nn.Identity()
            for st in state_size 
        ])
        
        flatten_size = np.sum(
                       np.asarray(
                        [
                        get_flatten_size(pr,st)
                        for pr,st in zip(self.preprocess,state_size)
                        ]
                        ))
        
        self.v = nn.Sequential(
            lin(flatten_size,node),
            nn.ReLU(),
            lin(node,node),
            nn.ReLU(),
            lin(node, 1)
        )
        
        self.q1 = nn.Sequential(
            lin(flatten_size + action_size[0],node),
            nn.ReLU(),
            lin(node,node),
            nn.ReLU(),
            lin(node, 1)
        )
        
        self.q2 = nn.Sequential(
            lin(flatten_size + action_size[0],node),
            nn.ReLU(),
            lin(node,node),
            nn.ReLU(),
            lin(node, 1)
        )

    def forward(self, xs,action):
        flats = [pre(x) for pre,x in zip(self.preprocess,xs)]
        cated = torch.cat(flats,dim=-1)
        cated_action = torch.cat(flats + [action],dim=-1)
        v = self.v(cated)
        q1 = self.q1(cated_action)
        q2 = self.q2(cated_action)
        return v, q1, q2
        
    def sample_noise(self):
        if not self.noisy:
            return
        for m in self.modules():
            if isinstance(m,NoisyLinear):
                m.sample_noise()