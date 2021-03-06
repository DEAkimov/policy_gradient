import os
import torch
import argparse
import gym
from tensorboardX import SummaryWriter
from src.networks import DenseSeparate, DenseShared, ConvSeparate, ConvShared
from src import Reinforce, A2C, PPO, atari_list, save, load, make_atari, play_episode, EnvPool


if __name__ == '__main__':
    def bool_type(x_str):
        x_str = x_str.lower()
        if x_str not in ['true', 'false']:
            raise BaseException('bool argument should be either \'true\' or \'false\'')
        return x_str == 'true'

    parser = argparse.ArgumentParser(description='Policy gradient runner')
    parser.add_argument("agent", type=str,
                        help="Agent type, one from {\'Reinforce\', \'A2C\', \'PPO\'}")
    parser.add_argument("environment", type=str,
                        help="Environment name. Only CartPole-v1 and Atari supported")

    parser.add_argument("--net_type", type=str, default='Shared',
                        help="Net type, one from {\'Shared\', \'Separate\'}")
    parser.add_argument("--optimizer", type=str, default='Adam',
                        help="Optimizer. Adam or SGD")
    parser.add_argument("--lr", type=float, default=1e-3,
                        help="Learning rate, float")
    parser.add_argument("--entropy_reg", type=float, default=1e-2,
                        help="Entropy regularization coefficient, float")
    parser.add_argument("--gamma", type=float, default=0.99,
                        help="Discount factor, from 0.0 to 1.0")
    parser.add_argument("--cuda", type=bool_type, default='false',
                        help="cuda. \'true\' or \'false\'")
    parser.add_argument("--train_steps", type=int, default=0,
                        help="number of training steps")
    # a2c specific arguments:
    parser.add_argument("--n_environments", type=int, default=16,
                        help="number of parallel environments, for A2C and PPO")
    parser.add_argument("--rollout_len", type=int, default=10,
                        help="number of steps in env_pool to form a batch in A2C or PPO")
    parser.add_argument("--normalize_advantage", type=bool_type, default='true',
                        help="if \'true\' advantage estimations will be normalized")
    # ppo specific arguments:
    parser.add_argument("--ppo_batch_size", type=int, default=16,
                        help="ppo batch size")
    parser.add_argument("--num_ppo_epochs", type=int, default=16,
                        help="number of ppo epoch")
    parser.add_argument("--ppo_eps", type=float, default=0.1,
                        help="ppo epsilon, some-what 'trust-region' size")
    parser.add_argument("--gae_lambda", type=float, default=10,
                        help="lambda parameter for generalized advantage estimation")

    parser.add_argument("--watch", type=int, default=0,
                        help="number of episodes to watch")
    args, remaining = parser.parse_known_args()

    print('================== Policy gradient training ==================')
    # init environment and net
    if args.environment == 'CartPole-v1':
        environment = gym.make(args.environment)
        if args.net_type == 'Shared':
            net = DenseShared(4, 128, 2)
        else:
            net = DenseSeparate(4, 128, 2)
    elif args.environment in atari_list:
        environment = make_atari(args.environment)
        if args.net_type == 'Shared':
            net = ConvShared(environment.action_space.n)
        else:
            net = ConvSeparate(environment.action_space.n)
    else:
        raise BaseException('Only CartPole-v1 and Atari supported')
    print('Environment: {}, agent: {}'.format(args.environment, args.agent))

    # init optimizer
    device = torch.device('cuda' if args.cuda else 'cpu')
    if args.optimizer == 'Adam':
        optimizer = torch.optim.Adam(net.parameters(), args.lr)
    elif args.optimizer == 'SGD':
        optimizer = torch.optim.SGD(net.parameters(), args.lr)
    else:
        raise BaseException('Only Adam and SGD supported')
    net.to(device)
    print('net: {}, optimizer: {}, lr: {}, entropy: {}'.format(
        args.net_type, args.optimizer, args.lr, args.entropy_reg
    ))

    # init writer
    log_string = 'logs/' + args.environment + '/' + args.agent + '/'
    if args.agent in ['A2C', 'PPO'] and args.normalize_advantage:
        log_string = log_string[:-1] + '_norm_A/'
    writer = SummaryWriter(log_string)
    if args.gamma < 0.0 or args.gamma > 1.0:
        raise BaseException('Discount factor must be from 0.0 to 1.0')
    if args.agent == 'Reinforce':
        agent = Reinforce(environment, net, device, optimizer, args.entropy_reg, writer, args.gamma)
    else:
        if args.environment == 'CartPole-v1':
            env_pool = EnvPool(gym.make, args.environment, args.n_environments, writer)
        else:
            env_pool = EnvPool(make_atari, args.environment, args.n_environments, writer)
        if args.agent == 'A2C':
            agent = A2C(env_pool, net, device, optimizer, args.entropy_reg, writer,
                        args.rollout_len, args.normalize_advantage, args.gamma)
        elif args.agent == 'PPO':
            agent = PPO(env_pool, net, device, optimizer, args.entropy_reg, writer,
                        args.rollout_len, args.normalize_advantage,
                        args.ppo_batch_size, args.num_ppo_epochs, args.ppo_eps, args.gae_lambda,
                        args.gamma)
        else:
            raise BaseException('wrong agent')

    # training:
    if args.train_steps > 0:
        print('========================= training ===========================')
        agent.train(args.train_steps)
        try:
            os.mkdir('./checkpoints/' + args.environment + '/')
        except FileExistsError:
            pass
        checkpoint = 'checkpoints/' + args.environment + '/' + args.agent + '.pth'
        save(agent, checkpoint)
        print('Training done. Checkpoint saved in \'{}\''.format(checkpoint))

    if args.watch > 0:
        if args.train_steps == 0:
            checkpoint = 'checkpoints/' + args.environment + '/' + args.agent + '.pth'
            load(checkpoint, agent)
        print('========================= watching ===========================')
        for _ in range(args.watch):
            print(play_episode(environment, agent, True))
    environment.close()
