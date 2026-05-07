请以E:\智能体\测试\optclaw里面的代码为基础，写一个client.py文件，用来创建对话智能体。

要求：

1 请在thread_data.py里，补充一个功能，记录用户名，用于用户信息隔离

2 采用langchain的create_agent，创建智能体。例子：

agent=create_agent(

    model=model,

    system_prompt="你好"

)

3  请增加一个提示词管理代码，prompt_manage.py，用于提取

1）用户身份信息

2）系统提示词

3）memory信息
