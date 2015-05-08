import sys
import traceback
import paramiko
import os
from time import sleep
import httplib
import string

# Arguments
sshPort = 22
testBaseFolder = "/home/iosintro/testing"
sshUser = "iosintro"
sshHost = "iosintro-bruegge.in.tum.de"
sshPassword = "2XXRR3Py"
testEnvName = "test_python"
testComposeFile = "production.yml"
testService = "node"
testServiceStartUpTime = 1
testServiceUrl = "/"
testServiceVerb = "GET"
testPrivatePort = 80

# Private variables
artifact = False
targetAbsPath = False
publicPort = False
success = False

# Helper
def indent(s):
    s = string.split(s, '\n')
    s = ['\t' + string.strip(line) for line in s]
    s = string.join(s, '\n')
    return s

# Get artifact
files = filter(os.path.isfile, os.listdir(os.curdir))
for f in files:
    if f.endswith(".zip"):
        artifact = (f, os.path.abspath(f))
        break
if not artifact:
    raise Exception('No artifact (zip) found!')

# Perform SSH operations
try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print("### Connect to Docker host at "+sshHost+" ###")
    client.connect(sshHost, sshPort, sshUser, sshPassword)

    chan = client.invoke_shell()

    channelLog = str()
    stage = 0

    while True:
        if chan.recv_ready():
            channelLog += chan.recv(1024)
        else:
            continue

        if chan.send_ready() and "[sudo] password" in channelLog and channelLog.rstrip().endswith(":"):
            print(indent(channelLog))
            print("### Enter SUDO password ###")
            channelLog = ""
            chan.sendall(sshPassword + "\n")

        elif chan.send_ready() and channelLog.rstrip().endswith("~$") and stage == 0:
            print(indent(channelLog))
            print("### PREPARE: Enter testing env ###")
            channelLog = ""
            chan.sendall('cd '+testBaseFolder+'\n')
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+os.path.basename(testBaseFolder)+"$") and stage == 1:
            print(indent(channelLog))
            print("### PREPARE: Create and cd to working directory ###")
            channelLog = ""
            chan.sendall('[ -d '+testEnvName+' ] || mkdir '+testEnvName+'\n')
            chan.sendall('cd '+testEnvName+'\n')
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 2:
            print(indent(channelLog))
            print("### PREPARE: Clean working directory ###")
            channelLog = ""
            chan.sendall('rm -rf *\n')
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 3:
            print(indent(channelLog))
            print("### PREPARE: Get absolute target path ###")
            channelLog = ""
            chan.sendall('pwd\n')
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 4:
            print(indent(channelLog))
            print("### PREPARE: Parse absolute target path ###")
            for line in channelLog.split("\n"):
                line = line.lstrip().rstrip()
                if line.startswith("/") and line.endswith("/"+testEnvName):
                    targetAbsPath = line
                    chan.sendall('\n')
                    stage += 1
                    channelLog = ""
                    break    

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 5:
            print(indent(channelLog))
            print("### COPY: Copy artifact ###")
            channelLog = ""
            sftp = client.open_sftp()
            sftp.put(artifact[1], os.path.join(targetAbsPath, artifact[0]))
            sftp.close()
            chan.sendall("ls -As\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 6:
            print(indent(channelLog))
            print("### COPY: Unzip artifact ###")
            channelLog = ""
            chan.sendall("unzip *.zip\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 7:
            print(indent(channelLog))
            print("### COPY: Remove artifact ###")
            channelLog = ""
            chan.sendall("rm *.zip\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 8:
            print(indent(channelLog))
            print("### RUN: Stop existing composition ###")
            channelLog = ""
            chan.sendall("sudo docker-compose -f "+testComposeFile+" -p="+testEnvName+" stop\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 9:
            print(indent(channelLog))
            print("### RUN: Remove existing composition ###")
            channelLog = ""
            chan.sendall("sudo docker-compose -f "+testComposeFile+" -p="+testEnvName+" rm -v --force\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 10:
            print(indent(channelLog))
            print("### RUN: Rebuild composition ###")
            channelLog = ""
            chan.sendall("sudo docker-compose -f "+testComposeFile+" -p="+testEnvName+" build\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 11:
            print(indent(channelLog))
            print("### RUN: Run composition ###")
            channelLog = ""
            chan.sendall("sudo docker-compose -f "+testComposeFile+" -p="+testEnvName+" up -d\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 12:
            print(indent(channelLog))
            print("### TEST: Get public port ###")
            channelLog = ""
            chan.sendall("sudo docker-compose -f "+testComposeFile+" -p="+testEnvName+" port "+testService+" "+str(testPrivatePort)+"\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 13:
            print(indent(channelLog))
            print("### TEST: Parse public port ###")
            for line in channelLog.split("\n"):
                line = line.lstrip().rstrip()
                if "0.0.0.0:" in line:
                    publicPort = line.split(":")
                    publicPort = int(publicPort[-1])
                    chan.sendall('\n')
                    stage += 1
                    channelLog = ""
                    break   

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 14:
            sleep(testServiceStartUpTime)
            print(indent(channelLog))
            print("### TEST: Make HTTP request ###")
            print("### "+testServiceVerb+" "+sshHost+":"+str(publicPort)+testServiceUrl+" (timeout 10sec) ###")

            try:
                channelLog = ""
                conn = httplib.HTTPConnection(sshHost, publicPort, timeout=10)
                conn.request(testServiceVerb, testServiceUrl)
                response = conn.getresponse()
                if response.status == httplib.OK:
                    print(indent("Test was successful!"))
                    success = True
                else:
                    print(indent(string.join(["Test failed!", response.getheaders(), response.read()], "\n")))
            except Exception as e:
                print(indent(string.join(["Test failed with exception!", e], "\n")))

            chan.sendall('\n')
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 15:
            print(indent(channelLog))
            print("### CLEAN: Stop composition ###")
            channelLog = ""
            chan.sendall("sudo docker-compose -f "+testComposeFile+" -p="+testEnvName+" stop\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 16:
            print(indent(channelLog))
            print("### CLEAN: Remove composition ###")
            channelLog = ""
            chan.sendall("sudo docker-compose -f "+testComposeFile+" -p="+testEnvName+" rm -v --force\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+testEnvName+"$") and stage == 17:
            print(indent(channelLog))
            print("### CLEAN: Enter testing env ###")
            channelLog = ""
            chan.sendall("cd "+testBaseFolder+"\n")
            stage += 1

        elif chan.send_ready() and channelLog.rstrip().endswith("/"+os.path.basename(testBaseFolder)+"$") and stage == 18:
            print(indent(channelLog))
            print("### CLEAN: Remove working directoy ###")
            channelLog = ""
            chan.sendall("rm -rf "+testEnvName+"\n")
            stage += 1

        elif stage > 18:
            print(indent(channelLog))
            break

    chan.close()
    client.close()

    if success:
        sys.exit(0)
    else:
        sys.exit(1)

except Exception as e:
    print("### Exception: %s: %s" % (e.__class__, e))
    traceback.print_exc()
    try:
        client.close()
    except:
        pass
    sys.exit(1)