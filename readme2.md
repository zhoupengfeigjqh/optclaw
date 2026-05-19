总任务：我有个需求，开发一个前端页面，用于和我的agent交互

1 optclaw是我后端的agent工程代码，里面的client.py是我调用agent的代码，请重点参考这个文件所提供的接口函数来开发前端功能

2 请将前端代码写在frontend里，需求如下：

1）前端请参考豆包的结构，需要有交互入口，历史对话记录查看和文件上传基本功能

2）整个交互必须是stream的流式输出

3）前端页面可切换模型list_model、切换思考模式（开启 or 关闭）和切换subagent模式（开启 or 关闭）

4）前端技术栈：nodejs和nginx

5）注意参数前后端的接口参数传递

3 提取后端工程代码需要的requirement.txt

4 构建docker-compose文件，用于后续打包和启动项目

5 千万不要修改optclaw里的代码

6 若要修改client.py，请告知我！
