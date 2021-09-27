import torch
import numpy as np

from torch_baselines.DQN.base_class import Q_Network_Family
from torch_baselines.C51.network import Model
from torch_baselines.common.losses import CategorialDistributionLoss

class C51(Q_Network_Family):
    def __init__(self, env, gamma=0.99, learning_rate=5e-4, buffer_size=50000, exploration_fraction=0.3, categorial_bar_n = 51,
                 exploration_final_eps=0.02, exploration_initial_eps=1.0, train_freq=1, batch_size=32, double_q=True,
                 dualing_model = False, n_step = 1, learning_starts=1000, target_network_update_freq=2000, prioritized_replay=False,
                 prioritized_replay_alpha=0.6, prioritized_replay_beta0=0.4, prioritized_replay_eps=1e-6, 
                 param_noise=False, verbose=0, tensorboard_log=None, _init_setup_model=True, policy_kwargs=None, 
                 full_tensorboard_log=False, seed=None):
        
        super(C51, self).__init__(env, gamma, learning_rate, buffer_size, exploration_fraction,
                 exploration_final_eps, exploration_initial_eps, train_freq, batch_size, double_q,
                 dualing_model, n_step, learning_starts, target_network_update_freq, prioritized_replay,
                 prioritized_replay_alpha, prioritized_replay_beta0, prioritized_replay_eps, 
                 param_noise, verbose, tensorboard_log, _init_setup_model, policy_kwargs, 
                 full_tensorboard_log, seed)
        
        self.categorial_bar_n = categorial_bar_n
        self.categorial_min = 0
        self.categorial_max = 30
        
        if _init_setup_model:
            self.setup_model() 
            
    def setup_model(self):
        self.policy_kwargs = {} if self.policy_kwargs is None else self.policy_kwargs
        self.categorial_bar = torch.linspace(self.categorial_min,self.categorial_max,self.categorial_bar_n).view(1,self.categorial_bar_n).to(self.device)
        self.bar_mean = ((self.categorial_bar[1:] + self.categorial_bar[:-1])/2.0).view(1,1,self.categorial_bar_n-1)
        self.delta_bar = torch.tensor((self.categorial_max - self.categorial_min)/(self.categorial_bar_n-1)).to(self.device)
        self.model = Model(self.observation_space,self.action_size,
                           dualing=self.dualing_model,noisy=self.param_noise,
                           bar_mean=self.bar_mean,
                           **self.policy_kwargs)
        self.target_model = Model(self.observation_space,self.action_size,
                                  dualing=self.dualing_model,noisy=self.param_noise,
                                  bar_mean=self.bar_mean,
                                  **self.policy_kwargs)
        self.model.train()
        self.model.to(self.device)
        self.target_model.load_state_dict(self.model.state_dict())
        self.target_model.train()
        self.target_model.to(self.device)
        
        self.optimizer = torch.optim.Adam(self.model.parameters(),lr=self.learning_rate)
        self.loss = CategorialDistributionLoss(categorial_bar=self.categorial_bar)
        
        print("----------------------model----------------------")
        print(self.model)
        print("-------------------------------------------------")
    
    def _train_step(self, steps):
        # Sample a batch from the replay buffer
        if self.prioritized_replay:
            data = self.replay_buffer.sample(self.batch_size,self.prioritized_replay_beta0)
        else:
            data = self.replay_buffer.sample(self.batch_size)
        obses = [torch.from_numpy(o).to(self.device).float() for o in data[0]]
        obses = [o.permute(0,3,1,2) if len(o.shape) == 4 else o for o in obses]
        actions = torch.from_numpy(data[1]).to(self.device).view(-1,1,1).repeat_interleave(self.n_support, dim=2)
        rewards = torch.from_numpy(data[2]).to(self.device).float().view(-1,1)
        nxtobses = [torch.from_numpy(o).to(self.device).float() for o in data[3]]
        nxtobses = [no.permute(0,3,1,2) if len(no.shape) == 4 else no for no in nxtobses]
        dones = (~(torch.from_numpy(data[4]).to(self.device))).float().view(-1,1)
        self.model.sample_noise()
        self.target_model.sample_noise()
        vals = self.model(obses).gather(1,actions)
        with torch.no_grad():
            
            if self.double_q:
                next_actions = (self.model(nxtobses)*self.model.bar_mean).mean(2),max(1)[1].view(-1,1,1).repeat_interleave(self.n_support, dim=2)
            else:
                next_actions = (self.target_model(nxtobses)*self.model.bar_mean).mean(2),max(1)[1].view(-1,1,1).repeat_interleave(self.n_support, dim=2)
            next_distribution = self.target_model(nxtobses).gather(1,next_actions)
            targets_categorial_bar = (dones * self.categorial_bar * self._gamma) + rewards
            
        '''
        if self.prioritized_replay:
            weights = torch.from_numpy(data[5]).to(self.device)
            indexs = data[6]
            new_priorities = np.abs((targets - vals).squeeze().detach().cpu().clone().numpy()) + self.prioritized_replay_eps
            self.replay_buffer.update_priorities(indexs,new_priorities)
            loss = self.loss(vals,targets).mean(-1)
            #loss = (weights*self.loss(vals,targets)).mean(-1)
        else:
            loss = self.loss(vals,targets).mean(-1)
        '''
        loss = self.loss()

        
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        if steps % self.target_network_update_freq == 0:
            self.target_model.load_state_dict(self.model.state_dict())
        
        if self.summary:
            self.summary.add_scalar("loss/qloss", loss, steps)

        return loss.detach().cpu().clone().numpy()
    
    def learn(self, total_timesteps, callback=None, log_interval=1000, tb_log_name="DQN",
              reset_num_timesteps=True, replay_wrapper=None):
        super().learn(total_timesteps, callback, log_interval, tb_log_name, reset_num_timesteps, replay_wrapper)