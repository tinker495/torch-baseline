import torch
import numpy as np

from torch_baselines.DDPG.base_class import Deterministic_Policy_Gradient_Family
from torch_baselines.SAC.network import Actor, Critic
from torch_baselines.common.losses import MSELosses, HuberLosses
from torch_baselines.common.utils import convert_states, hard_update, soft_update

class SAC(Deterministic_Policy_Gradient_Family):
    def __init__(self, env, gamma=0.99, learning_rate=5e-4, buffer_size=50000, action_noise = 0.1, train_freq=1, gradient_steps=1,
                 batch_size=32, policy_delay = 2, n_step = 1, learning_starts=1000, target_network_tau=0.99, prioritized_replay=False, 
                 prioritized_replay_alpha=0.6, prioritized_replay_beta0=0.4, prioritized_replay_eps=1e-6, 
                 param_noise=False, max_grad_norm = 1.0, log_interval=200, tensorboard_log=None, _init_setup_model=True, policy_kwargs=None, 
                 full_tensorboard_log=False, seed=None):
        
        super(SAC, self).__init__(env, gamma, learning_rate, buffer_size, train_freq, gradient_steps, batch_size, 
                 n_step, learning_starts, target_network_tau, prioritized_replay,
                 prioritized_replay_alpha, prioritized_replay_beta0, prioritized_replay_eps, 
                 param_noise, max_grad_norm, log_interval, tensorboard_log, _init_setup_model, policy_kwargs, 
                 full_tensorboard_log, seed)
        
        self.action_noise = action_noise
        self.target_action_noise = 0.2
        self.action_noise_clamp = 0.5
        self.policy_delay = policy_delay
        
        if _init_setup_model:
            self.setup_model()
            
    def actions(self,obs,befor_train):
        if not befor_train:
            with torch.no_grad():
                actions = np.clip(self.actor(convert_states(obs,self.device)).detach().cpu().clone().numpy() + 
                                np.random.normal(0,self.action_noise,size=(self.worker_size,self.action_size[0])),-1,1)
        else:
            actions = np.clip(np.random.normal(0,self.action_noise,size=(self.worker_size,self.action_size[0])),-1,1)
        return actions
            
    def setup_model(self):
        self.policy_kwargs = {} if self.policy_kwargs is None else self.policy_kwargs
        self.actor = Actor(self.observation_space,self.action_size,
                           noisy=self.param_noise, **self.policy_kwargs)
        self.critic = Critic(self.observation_space,self.action_size,
                           noisy=self.param_noise, **self.policy_kwargs)
        self.target_critic = Critic(self.observation_space,self.action_size,
                           noisy=self.param_noise, **self.policy_kwargs)
        self.actor.train()
        self.actor.to(self.device)
        self.critic.train()
        self.critic.to(self.device)
        self.target_critic.train()
        self.target_critic.to(self.device)
        hard_update(self.target_critic,self.critic)
        
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(),lr=self.learning_rate)
        self.critic_optimizer = torch.optim.Adam(self.critic.parameters(),lr=self.learning_rate)
        self.critic_loss = MSELosses()
        
        print("----------------------model----------------------")
        print(self.actor)
        print(self.critic)
        print(self.critic_loss)
        print("-------------------------------------------------")
    
    def _train_step(self, steps):
        # Sample a batch from the replay buffer
        if self.prioritized_replay:
            data = self.replay_buffer.sample(self.batch_size,self.prioritized_replay_beta0)
        else:
            data = self.replay_buffer.sample(self.batch_size)

        with torch.no_grad():
            obses = convert_states(data[0],self.device)
            actions = torch.tensor(data[1],dtype=torch.float32,device=self.device)
            rewards = torch.tensor(data[2],dtype=torch.float32,device=self.device).view(-1,1)
            nxtobses = convert_states(data[3],self.device)
            dones = (~torch.tensor(data[4],dtype=torch.bool,device=self.device)).float().view(-1,1)
            q1_pi, q2_pi, _ = self.critic(obses,self.actor(obses))
            _, _, target_vals = self.target_critic(nxtobses,actions)
            min_q_pi = torch.minimum(q1_pi,q2_pi)
            next_vals = dones * target_vals
            targets = (next_vals * self._gamma) + rewards
        
        q1, q2, vals = self.critic(obses,actions)
        
        if self.prioritized_replay:
            weights = torch.from_numpy(data[5]).to(self.device)
            indexs = data[6]
            new_priorities = np.abs((min_q_pi - vals).squeeze().detach().cpu().clone().numpy()) + \
                                + self.prioritized_replay_eps
            self.replay_buffer.update_priorities(indexs,new_priorities)
            val_loss = (weights*self.critic_loss(vals,min_q_pi)).mean(-1)
            q_loss1 = (weights*self.critic_loss(q1,target_vals)).mean(-1)
            q_loss2 = (weights*self.critic_loss(q2,target_vals)).mean(-1)
        else:
            val_loss = self.critic_loss(vals,min_q_pi).mean(-1)
            q_loss1 = self.critic_loss(q1,target_vals).mean(-1)
            q_loss2 = self.critic_loss(q2,target_vals).mean(-1)
        critic_loss = q_loss1 + q_loss2 + val_loss
        
        self.critic_optimizer.zero_grad(set_to_none=True)
        critic_loss.backward()
        self.critic_optimizer.step()
        
        if steps % self.policy_delay == 0:
            q1,_ = self.critic(obses,self.actor(obses))
            actor_loss = -q1.squeeze().mean(-1)
            
            self.actor_optimizer.zero_grad(set_to_none=True)
            actor_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.actor.parameters(), self.max_grad_norm)
            self.actor_optimizer.step()
        
            soft_update(self.target_actor,self.actor,self.target_network_tau)
            soft_update(self.target_critic,self.critic,self.target_network_tau)
            
            if self.summary and steps % self.log_interval == 0:
                self.summary.add_scalar("loss/actor_loss", actor_loss, steps)
        
        if self.summary and steps % self.log_interval == 0:
            self.summary.add_scalar("loss/critic_loss", critic_loss, steps)
            self.summary.add_scalar("loss/targets", targets.mean(), steps)

        return critic_loss.detach().cpu().clone().numpy()
    
    def learn(self, total_timesteps, callback=None, log_interval=1000, tb_log_name="SAC",
              reset_num_timesteps=True, replay_wrapper=None):
        super().learn(total_timesteps, callback, log_interval, tb_log_name, reset_num_timesteps, replay_wrapper)