"""
Description: Simple script with two AI agents that communicate with each other through messages using global variables.
"""

messages = []

def agent_function(agent):
    global messages
    while True:
        message = input(f'Agent {agent}: ')
        messages.append({'agent': agent, 'message': message})
        print(f'Agent {agent+1}:', messages[-1]['message'])

agent1_thread = Thread(target=agent_function, args=('1',))
agent2_thread = Thread(target=agent_function, args=('2',))

agent1_thread.start()
agent2_thread.start()