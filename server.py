from flask import Flask
from flask import Response
from flask import stream_with_context
import sys
sys.path.append('/home/adminuser/s3cfg/')
from s3cmd1 import cmd_ls
app = Flask(__name__)

@app.route('/getobject')
def home(url):
    req = requests.get(url, stream = True)
    return Response(stream_with_context(req.iter_content()), content_type = req.headers['content-type'])

@app.route('/listall')
def getAllBuckets():
	print "I am in"
	return Response(cmd_ls("ls"),content_type = req.headers['content-type']) 


cmd_ls("ls")

#if __name__ == '__main__':
#    app.run()
