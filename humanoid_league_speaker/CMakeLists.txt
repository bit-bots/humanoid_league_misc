cmake_minimum_required(VERSION 2.8.3)
project(humanoid_league_speaker)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  dynamic_reconfigure
  humanoid_league_msgs
  bitbots_docs
)

catkin_python_setup()

## Generate dynamic reconfigure parameters in the 'cfg' folder
generate_dynamic_reconfigure_options(
   cfg/speaker_params.cfg
)

catkin_package()

enable_bitbots_docs()
