#!/usr/bin/env python3

import socket
import struct
import threading
from numpy import double
from typing import List, Optional, Tuple

import rclpy
import tf2_ros
from ament_index_python.packages import get_package_share_directory
from bitbots_utils.utils import get_parameter_dict, get_parameters_from_other_node
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist, TwistWithCovarianceStamped
from humanoid_league_msgs.msg import GameState, ObstacleRelative, ObstacleRelativeArray, Strategy, TeamData
from numpy import double
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import Float32, Header
from tf2_geometry_msgs import PointStamped, PoseStamped

from humanoid_league_team_communication.communication import SocketCommunication
from humanoid_league_team_communication.robocup_extension_pb2 import Message
from humanoid_league_team_communication.converter.robocup_protocol_converter import RobocupProtocolConverter


class HumanoidLeagueTeamCommunication:

    def __init__(self):
        self._package_path = get_package_share_directory("humanoid_league_team_communication")
        self.node = Node("team_comm", automatically_declare_parameters_from_overrides=True)
        self.logger = self.node.get_logger()
        self.protocol_converter = RobocupProtocolConverter()

        self.logger.info("Initializing humanoid_league_team_communication...")

        params_blackboard = get_parameters_from_other_node(self.node, "parameter_blackboard", ['bot_id', 'team_id'])
        self.player_id = params_blackboard['bot_id']
        self.team_id = params_blackboard['team_id']

        self.socket_communication = SocketCommunication(self.node, self.logger, self.team_id, self.player_id)

        self.rate = self.node.get_parameter('rate').get_parameter_value().integer_value
        self.lifetime = self.node.get_parameter('lifetime').get_parameter_value().integer_value
        self.avg_walking_speed = self.node.get_parameter('avg_walking_speed').get_parameter_value().double_value

        self.topics = get_parameter_dict(self.node, 'topics')
        self.map_frame = self.node.get_parameter('map_frame').get_parameter_value().string_value

        self.create_publishers()
        self.create_subscribers()

        self.set_state_defaults()

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self.node)

        self.try_to_establish_connection()
        self.run_spin_in_thread()

        self.node.create_timer(1 / self.rate, self.send_message)
        self.receive_forever()

    def run_spin_in_thread(self):
        # Necessary in ROS2, else we are forever stuck receiving messages
        thread = threading.Thread(target=rclpy.spin, args=[self.node], daemon=True)
        thread.start()

    def set_state_defaults(self):
        self.gamestate: GameState = None
        self.pose: PoseWithCovarianceStamped = None
        self.cmd_vel: Twist = None
        self.cmd_vel_time = Time(nanoseconds=0, clock_type=self.node.get_clock().clock_type)
        self.ball: Optional[PointStamped] = None
        self.ball_velocity: Tuple[float, float, float] = (0, 0, 0)
        self.ball_covariance: List[double] = None
        self.strategy: Strategy = None
        self.strategy_time = Time(nanoseconds=0, clock_type=self.node.get_clock().clock_type)
        self.time_to_ball: float = None
        self.time_to_ball_time = Time(nanoseconds=0, clock_type=self.node.get_clock().clock_type)
        self.obstacles: ObstacleRelativeArray = None
        self.move_base_goal: PoseStamped = None

    def try_to_establish_connection(self):
        # we will try multiple times till we manage to get a connection
        while rclpy.ok() and not self.socket_communication.is_setup():
            self.socket_communication.establish_connection()
            self.node.get_clock().sleep_for(Duration(seconds=1))
            rclpy.spin_once(self.node)

    def create_publishers(self):
        self.team_data_publisher = self.node.create_publisher(TeamData, self.topics['team_data_topic'], 1)

    def create_subscribers(self):
        self.node.create_subscription(GameState, self.topics['gamestate_topic'], self.gamestate_cb, 1)
        self.node.create_subscription(PoseWithCovarianceStamped, self.topics['pose_topic'], self.pose_cb, 1)
        self.node.create_subscription(Twist, self.topics['cmd_vel_topic'], self.cmd_vel_cb, 1)
        self.node.create_subscription(PoseWithCovarianceStamped, self.topics['ball_topic'], self.ball_cb, 1)
        self.node.create_subscription(TwistWithCovarianceStamped, self.topics['ball_velocity_topic'],
                                      self.ball_velocity_cb, 1)
        self.node.create_subscription(Strategy, self.topics['strategy_topic'], self.strategy_cb, 1)
        self.node.create_subscription(Float32, self.topics['time_to_ball_topic'], self.time_to_ball_cb, 1)
        self.node.create_subscription(ObstacleRelativeArray, self.topics['obstacle_topic'], self.obstacle_cb, 1)
        self.node.create_subscription(PoseStamped, self.topics['move_base_goal_topic'], self.move_base_goal_cb, 1)

    def gamestate_cb(self, msg: GameState):
        self.gamestate = msg

    def pose_cb(self, msg: PoseWithCovarianceStamped):
        self.pose = msg

    def cmd_vel_cb(self, msg: Twist):
        self.cmd_vel = msg
        self.cmd_vel_time = self.get_current_time().to_msg()

    def strategy_cb(self, msg: Strategy):
        self.strategy = msg
        self.strategy_time = self.get_current_time().to_msg()

    def time_to_ball_cb(self, msg: float):
        self.time_to_ball = msg.data
        self.time_to_ball_time = self.get_current_time().to_msg()

    def move_base_goal_cb(self, msg: PoseStamped):
        self.move_base_goal = msg

    def obstacle_cb(self, msg: ObstacleRelativeArray):

        def transform_to_map(obstacle: ObstacleRelative):
            obstacle_pose = PoseStamped(header=msg.header, pose=obstacle.pose.pose.pose)
            try:
                obstacle_map = self.tf_transform(obstacle_pose)
                obstacle.pose.pose.pose = obstacle_map.pose
                return obstacle
            except tf2_ros.TransformException:
                self.logger.error("TeamComm: Could not transform obstacle to map frame")

        self.obstacles = ObstacleRelativeArray(header=msg.header)
        self.obstacles.header.frame_id = self.map_frame
        self.obstacles.obstacles = list(map(transform_to_map, msg.obstacles))

    def ball_cb(self, msg: PoseWithCovarianceStamped):
        ball_point = PointStamped(header=msg.header, point=msg.pose.pose.position)
        try:
            self.ball = self.tf_transform(ball_point)
            self.ball_covariance = msg.pose.covariance
        except tf2_ros.TransformException:
            self.logger.error("TeamComm: Could not transform ball to map frame")
            self.ball = None

    def ball_velocity_cb(self, msg: TwistWithCovarianceStamped):
        self.ball_velocity = (msg.twist.twist.linear.x, msg.twist.twist.linear.y, msg.twist.twist.angular.z)

    def tf_transform(self, field, timeout_in_ns=0.3e9):
        return self.tf_buffer.transform(field, self.map_frame, timeout=Duration(nanoseconds=timeout_in_ns))

    def receive_forever(self):
        while rclpy.ok():
            try:
                message = self.socket_communication.receive_message()
            except (struct.error, socket.timeout):
                continue

            if message:
                self.handle_message(message)

    def handle_message(self, string_message: bytes):
        message = Message()
        message.ParseFromString(string_message)

        if self.should_message_be_discarded(message):
            self.logger.info("Discarding msg by player {} in team {} at {}".format(message.current_pose.player_id,
                                                                                   message.current_pose.team,
                                                                                   message.timestamp.seconds))
            return

        team_data = self.protocol_converter.convert_from_message(message, self.create_team_data())
        self.team_data_publisher.publish(team_data)

    def send_message(self):
        if not self.is_robot_allowed_to_send_message():
            self.logger.info("Not allowed to send message")
            return

        now = self.get_current_time()
        msg = self.create_empty_message(now)
        is_still_valid = lambda time: now - Time.from_msg(time) < Duration(seconds=self.lifetime)
        message = self.protocol_converter.convert_to_message(self, msg, is_still_valid)
        self.socket_communication.send_message(message.SerializeToString())

    def create_empty_message(self, now: Time) -> Message:
        message = Message()
        seconds, nanoseconds = now.seconds_nanoseconds()
        message.timestamp.seconds = seconds
        message.timestamp.nanos = nanoseconds
        return message

    def create_team_data(self) -> TeamData:
        return TeamData(header=self.create_header_with_own_time())

    def create_header_with_own_time(self) -> Header:
        return Header(stamp=self.get_current_time().to_msg(), frame_id=self.map_frame)

    def should_message_be_discarded(self, message: Message) -> bool:
        player_id = message.current_pose.player_id
        team_id = message.current_pose.team

        isOwnMessage = player_id == self.player_id
        isMessageFromOpositeTeam = team_id != self.team_id

        return isOwnMessage or isMessageFromOpositeTeam

    def is_robot_allowed_to_send_message(self) -> bool:
        return self.gamestate and not self.gamestate.penalized

    def get_current_time(self) -> Time:
        return self.node.get_clock().now()


def main():
    rclpy.init(args=None)
    HumanoidLeagueTeamCommunication()


if __name__ == '__main__':
    main()
