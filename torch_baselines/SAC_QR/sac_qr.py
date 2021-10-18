import torch
import numpy as np

from torch_baselines.DDPG.base_class import Deterministic_Policy_Gradient_Family
from torch_baselines.SAC_QR.network import Actor, Critic, Value
from torch_baselines.common.losses import QRHuberLosses
from torch_baselines.common.utils import convert_tensor, hard_update, soft_update

class SAC_QR(Deterministic_Policy_Gradient_Family):
    def __init__(self, env, gamma=0.99, learning_rate=5e-4, buffer_size=50000, n_support = 64, train_freq=1, gradient_steps=1, ent_coef = 1e-3,
                 batch_size=32, policy_delay = 2, n_step = 1, learning_starts=1000, target_network_tau=0.99, prioritized_replay=False, 
                 prioritized_replay_alpha=0.6, prioritized_replay_beta0=0.4, prioritized_replay_eps=1e-6, risk_avoidance = 0,
                 param_noise=False, max_grad_norm = 1.0, log_interval=200, tensorboard_log=None, _init_setup_model=True, policy_kwargs=None, 
                 full_tensorboard_log=False, seed=None):
        
        super(SAC_QR, self).__init__(env, gamma, learning_rate, buffer_size, train_freq, gradient_steps, batch_size, 
                 n_step, learning_starts, target_network_tau, prioritized_replay,
                 prioritized_replay_alpha, prioritized_replay_beta0, prioritized_replay_eps, 
                 param_noise, max_grad_norm, log_interval, tensorboard_log, _init_setup_model, policy_kwargs, 
                 full_tensorboard_log, seed)
        
        self.n_support = n_support
        self.risk_avoidance = risk_avoidance
        self.policy_delay = policy_delay
        self.ent_coef = ent_coef
        
        if _init_setup_model:
            self.setup_model()
            
            
    def setup_model(self):
        self.policy_kwargs = {} if self.policy_kwargs is None else self.policy_kwargs
        self.actor = Actor(self.observation_space,self.action_size,
                           noisy=self.param_noise, **self.policy_kwargs)
        self.critic = Critic(self.observation_space,self.action_size,
                           noisy=self.param_noise, **self.policy_kwargs)
        self.value = Value(self.observation_space, noisy=self.param_noise, **self.policy_kwargs)
        self.target_value = Value(self.observation_space, noisy=self.param_noise, **self.policy_kwargs)
        self.actor.train()
        self.actor.to(self.device)
        self.critic.train()
        self.critic.to(self.device)
        self.value.train()
        self.value.to(self.device)
        self.target_value.train()
        self.target_value.to(self.device)
        self.actor_param = list(self.actor.parameters())
        self.main_param = list(self.value.parameters())
        self.target_param = list(self.target_value.parameters())
        hard_update(self.target_param,self.main_param)
        
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(),lr=self.learning_rate)
        self.critic_optimizer = torch.optim.Adam(self.critic.parameters(),lr=self.learning_rate)
        self.value_optimizer = torch.optim.Adam(self.value.parameters(),lr=self.learning_rate)
        
        self.critic_loss = QRHuberLosses()
        self.quantile = torch.arange(0.5 / self.n_support,1, 1 / self.n_support,device=self.device,requires_grad=False).unsqueeze(0)
        self._quantile = self.quantile.unsqueeze(2)
        if self.risk_avoidance == 'auto':
            pass
        elif self.risk_avoidance == 'normal':
            self.sample_risk_avoidance = True
        else:
            self.risk_avoidance = float(self.risk_avoidance)
            #self.grad_mul = (self.quantile.view(1,self.n_support) < 0.1).float()/0.1
            self.grad_mul = 1.0 - self.risk_avoidance*(2.0*self.quantile.view(1,self.n_support) - 1.0)
        
        print("----------------------model----------------------")
        print(self.actor)
        print(self.critic)
        print(self.critic_loss)
        print("-------------------------------------------------")
    
    def _train_step(self, steps, grad_step):
        # Sample a batch from the replay buffer
        step = (steps + grad_step)
        if self.prioritized_replay:
            data = self.replay_buffer.sample(self.batch_size,self.prioritized_replay_beta0)
        else:
            data = self.replay_buffer.sample(self.batch_size)
        obses = convert_tensor(data[0],self.device)
        actions = torch.tensor(data[1],dtype=torch.float32,device=self.device)
        rewards = torch.tensor(data[2],dtype=torch.float32,device=self.device).view(-1,1)
        nxtobses = convert_tensor(data[3],self.device)
        dones = (~torch.tensor(data[4],dtype=torch.bool,device=self.device)).float().view(-1,1)
        
        with torch.no_grad():
            next_vals = dones * self.target_value(nxtobses)
            targets = (self._gamma * next_vals) + rewards
            logit_valid_tile = targets.unsqueeze(1).repeat_interleave(self.n_support, dim=1)
        q1, q2 = self.critic(obses,actions)
        
        
        theta1_loss_tile = q1.unsqueeze(2).repeat_interleave(self.n_support, dim=2)
        theta2_loss_tile = q2.unsqueeze(2).repeat_interleave(self.n_support, dim=2)
        
        if self.prioritized_replay:
            pass
        else:
            q_loss1 = self.critic_loss(theta1_loss_tile,logit_valid_tile,self._quantile).mean()
            q_loss2 = self.critic_loss(theta2_loss_tile,logit_valid_tile,self._quantile).mean()
        critic_loss = q_loss1 + q_loss2
        self.lossque.append(critic_loss.detach().cpu().clone().numpy())
        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        self.critic_optimizer.step()
        
        policy, log_prob, mu, log_std = self.actor.update_data(obses)
        qf1_pi, qf2_pi = self.critic(obses, policy)
        if step % self.policy_delay == 0:
            
            actor_loss = (self.ent_coef * log_prob - qf1_pi.mean(-1)).squeeze().mean() + 0.001 * (mu.pow(2).mean() + log_std.pow(2).mean())
            self.actor_optimizer.zero_grad()
            actor_loss.backward()
            if self.max_grad_norm > 0:
                torch.nn.utils.clip_grad_norm_(self.actor_param, self.max_grad_norm)
            self.actor_optimizer.step()
        
            soft_update(self.target_param,self.main_param,self.target_network_tau)
            
            if self.summary and step % self.log_interval == 0:
                self.summary.add_scalar("loss/actor_loss", actor_loss, steps)
                
        vf = self.value(obses)
        
        with torch.no_grad():
            vf_target = torch.minimum(qf1_pi,qf2_pi) - (self.ent_coef * log_prob)
            vf_target_tile = vf_target.unsqueeze(1).repeat_interleave(self.n_support, dim=1)

        theta_loss_tile = vf.unsqueeze(2).repeat_interleave(self.n_support, dim=2)
        vf_loss = self.critic_loss(theta_loss_tile, vf_target_tile, self._quantile).mean()

        self.value_optimizer.zero_grad()
        vf_loss.backward()
        self.value_optimizer.step()
        
        if self.summary and step % self.log_interval == 0:
            self.summary.add_scalar("loss/critic_loss", critic_loss, steps)
            self.summary.add_scalar("loss/targets", targets.mean(), steps)
    
    def actions(self,obs,befor_train):
        if not befor_train:
            with torch.no_grad():
                actions = self.actor.action(convert_tensor(obs,self.device)).detach().cpu().clone().numpy()
        else:
            actions = np.random.uniform(-1,1,size=(self.worker_size,self.action_size[0]))
        return actions
    
    def learn(self, total_timesteps, callback=None, log_interval=1000, tb_log_name="SAC_QR",
              reset_num_timesteps=True, replay_wrapper=None):
        if self.sample_risk_avoidance:
            tb_log_name = tb_log_name + "_{}".format(self.risk_avoidance)
        else:
            tb_log_name = tb_log_name + "_{:.2f}".format(self.risk_avoidance)
        super().learn(total_timesteps, callback, log_interval, tb_log_name, reset_num_timesteps, replay_wrapper)