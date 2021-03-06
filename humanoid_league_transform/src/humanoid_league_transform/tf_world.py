#!/usr/bin/env python3
"""
Tool to transform gazebo objects
"""
import rospy
import tf
from geometry_msgs.msg import TransformStamped, PoseWithCovarianceStamped
from gazebo_msgs.msg import ModelStates
from humanoid_league_msgs.msg import PoseWithCertaintyArray, PoseWithCertainty


class TFWorld(object):
    def __init__(self):
        rospy.init_node("world_transformer")
        rospy.Subscriber("/gazebo/model_states", ModelStates, self._callback, queue_size=1, tcp_nodelay=True)

        self.robot_pub = rospy.Publisher("amcl_pose", PoseWithCovarianceStamped, queue_size=1, tcp_nodelay=True)
        self.robo_msg = PoseWithCovarianceStamped()

        self.balls_pub = rospy.Publisher("balls_relative", PoseWithCertaintyArray, queue_size=1, tcp_nodelay=True)
        self.balls = []
        rospy.spin()


    def _callback(self, msg):
        br = tf.TransformBroadcaster()
        for i in range(len(msg.name)):
            if msg.name[i] == "/":
                transform = TransformStamped()
                transform.header.frame_id = "world"
                transform.header.stamp = rospy.Time.now()
                transform.child_frame_id = "base_link"
                transform.transform.translation = msg.pose[i].position
                transform.transform.rotation = msg.pose[i].orientation
                br.sendTransformMessage(transform)

                self.robo_msg.pose.pose = msg.pose[i]
                self.robo_msg.header.stamp = rospy.Time.now()
                self.robo_msg.header.frame_id = "world"
                self.robot_pub.publish(self.robo_msg)

            elif msg.name[i] == "teensize_ball":
                transform = TransformStamped()
                transform.header.frame_id = "world"
                transform.header.stamp = rospy.Time.now()
                transform.child_frame_id = "ball"
                transform.transform.translation = msg.pose[i].position
                transform.transform.rotation = msg.pose[i].orientation
                br.sendTransformMessage(transform)

                ball_msg = PoseWithCertainty()
                ball_msg.pose.pose.position.x = msg.pose[i].position.x
                ball_msg.pose.pose.position.y = msg.pose[i].position.y
                ball_msg.pose.pose.position.z = msg.pose[i].position.z
                ball_msg.pose.pose.orientation.x = 0
                ball_msg.pose.pose.orientation.y = 0
                ball_msg.pose.pose.orientation.z = 0
                ball_msg.pose.pose.orientation.w = 1
                ball_msg.pose.covariance = [1]*36
                ball_msg.confidence = 1.0
                self.balls.append(ball_msg)

        balls_msg = PoseWithCertaintyArray()
        balls_msg.header.frame_id = "world"
        balls_msg.header.stamp = rospy.Time.now()
        balls_msg.poses = self.balls
        self.balls_pub.publish(balls_msg)


        transform = TransformStamped()
        transform.header.frame_id = "world"
        transform.header.stamp = rospy.Time.now()
        transform.child_frame_id = "map"

        transform.transform.translation.x = -10.15/2
        transform.transform.translation.y = -7.13/2
        transform.transform.translation.z = 0
        transform.transform.rotation.x = 0
        transform.transform.rotation.y = 0
        transform.transform.rotation.z = 0
        transform.transform.rotation.w = 1
        br.sendTransformMessage(transform)


if __name__ == "__main__":
    TFWorld()
