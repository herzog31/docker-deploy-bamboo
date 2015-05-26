#!/usr/bin/env python

'''
Docker Deploy Script
     for Bamboo     

@author Mark J. Becker <mjb@marb.ec>
'''

from threading import Thread
import sys
import traceback
import paramiko
import os
import math
from time import sleep
import httplib
import string

### Arguments from Bamboo environment
# MODE
# - "CLEAR" remove existing compositions
# - "DEPLOY" deploy composition
# - "TEST" test composititon
# - "REMOVE" remove composition
# or any combination, e.g. DEPLOY,TEST
testMode = os.getenv('bamboo_docker_mode', "CLEAR,DEPLOY,TEST,REMOVE")

# SSH port
# DEFAULT 22
sshPort = int(os.getenv('bamboo_docker_sshport', 22))

# Bamboo working directory
testWorkingDirectory = os.getenv('bamboo_working_directory')

# Test folder, where to deploy build artifacts
testBaseFolder = os.getenv('bamboo_docker_path')

# SSH user
sshUser = os.getenv('bamboo_docker_user')

# SSH host
sshHost = os.getenv('bamboo_docker_hostname')

# SSH password
sshPassword = os.getenv('bamboo_docker_password')

# Env name, e.g. test_14
# DEFAULT test_default
testEnvName = os.getenv('bamboo_deploy_environment', "test_"+os.getenv('bamboo_buildNumber', 'default')).lower()

# Compose file, e.g. production.yml
testComposeFile = os.getenv('bamboo_docker_composeFile')

# Service to test, name from compose file, e.g. node
testService = os.getenv('bamboo_docker_test_service')

# Service start up time in secs, wait before executing test
# DEFAULT 5
testServiceStartUpTime = int(os.getenv('bamboo_docker_test_timeout', 5))

# Test URL, which URL to test
# DEFAULT /
testServiceUrl = os.getenv('bamboo_docker_test_url', "/")

# Test Verb, which HTTP method used for testing
# DEFAULT GET
testServiceVerb = os.getenv('bamboo_docker_test_verb', "GET")

# Test Port, private port to test
# DEFAULT 80
testPrivatePort = os.getenv('bamboo_docker_test_privatePort', '80')

# Indent string helper
def indent(s):
    s = string.split(s, '\n')
    s = ['\t' + string.strip(line) for line in s]
    s = string.join(s, '\n')
    return s

# SSH Reader Thread
# Read stdout & stderr from SSH server
class SSHReader(Thread):
    def __init__(self, channel):
        super(SSHReader, self).__init__()
        self.channel = channel
        self.running = True

    def run(self):
        global sshChannelOut
        global sshChannelErr
        while True and self.running:
            sleep(0.1)
            # Read from SSH stdout
            if self.channel.recv_ready():
                sshChannelOut += self.channel.recv(1024)

            # Read from SSH stderr
            if self.channel.recv_stderr_ready():
                sshChannelErr += self.channel.recv_stderr(1024)

    def stop(self):
        self.running = False

# Docker Deploy SSH Client
class DockerDeployClient():
    def __init__(self):
        self.reader = None
        self.channel = None
        self.artifact = None
        # Command to check if command was successful
        self.endCommand = "echo \"EXIT CODE $?\";"
        self.endCommandPattern = "EXIT CODE"

    # Connect to ssh host
    def connect(self, host, user, password, port):
        self.sshHost = host
        self.sshUser = user
        self.sshPassword = password
        self.sshPort = port

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.sshHost, self.sshPort, self.sshUser, self.sshPassword)

        self.channel = self.client.invoke_shell()
        self.channel.settimeout(30)

        return True

    # Start SSH Reader
    def listen(self):
        self.reader = SSHReader(self.channel)
        self.reader.start()

    # Enter sudo password if asked
    def enterSudoPassword(self):
        global sshChannelOut

        if "[sudo] password" in sshChannelOut and sshChannelOut.rstrip().endswith(":") and self.channel.send_ready():
            print("### Enter SUDO password ###")
            self.channel.sendall(self.sshPassword + "\n")
            return True
        return False

    # Find zip file in given directory
    def findLocalArtifact(self, directory):
        # Get artifact, should be a zip file stored in the working folder
        files = filter(os.path.isfile, os.listdir(testWorkingDirectory))
        for f in files:
            if f.endswith(".zip"):
                self.artifact = (f, os.path.abspath(f))
                return self.artifact

        raise Exception('No artifact (zip) found!')
        return False

    # Change folder
    def goToFolder(self, target):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('cd '+target+';\n'+self.endCommand+'\n')

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not change directory to '+target+'!')
        return False

    # Create new folder
    def createFolder(self, target):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('[ -d '+target+' ] || mkdir '+target+';\n'+self.endCommand+'\n')

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not create directory '+target+'!')
        return False

    # Remove everything in current folder
    def cleanFolder(self):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('rm -rf *;\n'+self.endCommand+'\n')

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not clean directory!')
        return False

    # Get absolute path to given directory
    def getAbsolutePath(self, target):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('pwd;\n'+self.endCommand+'\n')

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            for line in sshChannelOut.split("\n"):
                line = line.strip()
                if line.startswith("/") and line.endswith("/"+target):
                    return line

        raise Exception('Could not get absolute path to '+target+'!')
        return False

    # Copy file from local source to remote target
    def copyArtifact(self, source, target):

        sftp = self.client.open_sftp()
        sftp.put(source[1], os.path.join(target, source[0]))
        sftp.close()

        return True

    # Unzip given file
    def unzipArtifact(self, target):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('unzip '+target+';\n'+self.endCommand+'\n')

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not unzip '+target+'!')
        return False

    # Remove given file
    def removeArtifact(self, target):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('rm '+target+';\n'+self.endCommand+'\n')

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not delete '+target+'!')
        return False

    # Stop docker composition with given yml config and prefix
    def stopComposition(self, yml, prefix):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('sudo docker-compose -f '+yml+' -p='+prefix+' stop; '+self.endCommand+'\n')
        sudo = True

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            if sudo and self.enterSudoPassword():
                sudo = False
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not stop composition '+yml+', '+prefix+'!')
        return False

    # Remove docker composition with given yml config and prefix
    # set volumes to True to force delete all volumes
    def removeComposition(self, yml, prefix, volumes):
        global sshChannelOut
        sshChannelOut = ""

        if volumes:
            self.channel.sendall('sudo docker-compose -f '+yml+' -p='+prefix+' rm -v --force; '+self.endCommand+'\n')
        else:
            self.channel.sendall('sudo docker-compose -f '+yml+' -p='+prefix+' rm --force; '+self.endCommand+'\n')
        sudo = True

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            if sudo and self.enterSudoPassword():
                sudo = False
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not remove composition '+yml+', '+prefix+'!')
        return False

    # Build docker composition with given yml config and prefix
    def buildComposition(self, yml, prefix):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('sudo docker-compose -f '+yml+' -p='+prefix+' build; '+self.endCommand+'\n')
        sudo = True

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            if sudo and self.enterSudoPassword():
                sudo = False
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not build composition '+yml+', '+prefix+'!')
        return False

    # Run docker composition with given yml config and prefix
    def runComposition(self, yml, prefix):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('sudo docker-compose -f '+yml+' -p='+prefix+' up -d; '+self.endCommand+'\n')
        sudo = True

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            if sudo and self.enterSudoPassword():
                sudo = False
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not start composition '+yml+', '+prefix+'!')
        return False

    # Get public port of composition with given yml config, prefix, service name and its private port
    def getPortMapping(self, yml, prefix, service, privatePort):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('sudo docker-compose -f '+yml+' -p='+prefix+' port '+service+' '+str(privatePort)+'; '+self.endCommand+'\n')
        sudo = True

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            if sudo and self.enterSudoPassword():
                sudo = False
            sleep(0.1)

        self.outputChannel()

        if "No container found" in sshChannelOut:
            raise Exception('Service '+service+' not running!')
            return False

        if self.parseExitCode() == 0:
            for line in sshChannelOut.split("\n"):
                line = line.strip()
                if "0.0.0.0:" in line:
                    publicPort = line.split(":")
                    return int(publicPort[-1])

        raise Exception('Could not get port mapping composition '+yml+', '+prefix+' service '+service+'!')
        return False

    # Make HTTP request to host:port with verb, url and startup time
    def makeHTTPRequest(self, host, port, verb, url, startup):
        response = None
        iterations = int(math.ceil(startup / 0.5))

        for i in range(0, iterations):
            sleep(0.5)
            try:
                print(indent("Test #"+str(i)))
                conn = httplib.HTTPConnection(host, port, timeout=10)
                conn.request(verb, url)
                response = conn.getresponse()
                if response.status == httplib.OK:
                    print(indent("Test was successful!"))
                    return True
                else:
                    print(indent("Test failed: Status "+str(response.status)+"!"))
            except Exception as e:
                print(indent("Test failed: Not reachable!"))
        
        print(indent('Test failed ('+verb+' '+host+':'+str(port)+url+')!'))
        return False

    # Remove given folder
    def removeFolder(self, target):
        global sshChannelOut
        sshChannelOut = ""

        self.channel.sendall('rm -rf '+target+'; '+self.endCommand+'\n')

        while not (self.endCommandPattern in sshChannelOut and sshChannelOut.rstrip().endswith("$")):
            sleep(0.1)

        self.outputChannel()

        if self.parseExitCode() == 0:
            return True

        raise Exception('Could not delete folder '+target+'!')
        return False

    # Stop stdout & stderr reader and close SSH connection
    def close(self):
        # Stop stdout & stderr reader
        self.reader.stop()

        # Close connection
        self.channel.close()
        self.client.close()
        return True

    # Parse exit code of previous command
    def parseExitCode(self):
        global sshChannelOut

        for line in sshChannelOut.split("\n"):
            line = line.strip()
            if line.startswith(self.endCommandPattern):
                code = line[len(self.endCommandPattern):]
                code = code.strip()
                return int(code)
        return False

    # Output current stdout
    def outputChannel(self):
        global sshChannelOut
        print(indent(sshChannelOut))

    # Output current stderr
    def outputError(self):
        print(self.channelErr)

### MAIN ###
try:

    # Shared variable for stdout
    sshChannelOut = None
    # Shared variable for stderr
    sshChannelErr = None

    success = True

    client = DockerDeployClient()
    print("### Connect to Docker host ("+sshUser+"@"+sshHost+":"+str(sshPort)+") ###")
    client.connect(sshHost, sshUser, sshPassword, sshPort)
    print("### Listen to stdout & stderr ###")
    client.listen()
    print("### Find build artifact ###")
    artifact = client.findLocalArtifact(testWorkingDirectory)
    print("#### Artifact: "+ artifact[0])
    print("### Go to testing folder ###")
    client.goToFolder(testBaseFolder)
    print("### Create working directory ###")
    client.createFolder(testEnvName)
    print("### Go to working directory ###")
    client.goToFolder(testEnvName)
    print("### Clean working directory ###")
    client.cleanFolder()
    print("### Get absolute path ###")
    path = client.getAbsolutePath(testEnvName)
    print("#### Path: " + path)
    print("### Copy Artifact ###")
    print("#### COPY " + artifact[0] + " FROM " + artifact[1] + " TO " + path)
    client.copyArtifact(artifact, path)
    print("### Unzip Artifact ###")
    client.unzipArtifact(artifact[0])
    print("### Delete Artifact ###")
    client.removeArtifact(artifact[0])
    # MODE CLEAR
    if "CLEAR" in testMode:
        print("### Stop existing composition ###")
        client.stopComposition(testComposeFile, testEnvName)
        print("### Remove existing composition ###")
        client.removeComposition(testComposeFile, testEnvName, True)
    # MODE DEPLOY
    if "DEPLOY" in testMode:
        print("### Build composition ###")
        client.buildComposition(testComposeFile, testEnvName)
        print("### Run composition ###")
        client.runComposition(testComposeFile, testEnvName)
    # MODE TEST
    if "TEST" in testMode:
        print("### Get port mapping ###")
        publicPort = client.getPortMapping(testComposeFile, testEnvName, testService, testPrivatePort)
        print("#### Public port: " + str(publicPort))
        print("### Make HTTP request ###")
        success = client.makeHTTPRequest(sshHost, publicPort, testServiceVerb, testServiceUrl, testServiceStartUpTime)
    # MODE REMOVE
    if "REMOVE" in testMode:
        print("### Stop composition ###")
        client.stopComposition(testComposeFile, testEnvName)
        print("### Remove composition ###")
        client.removeComposition(testComposeFile, testEnvName, True)
    print("### Go to testing folder ###")
    client.goToFolder(testBaseFolder)
    print("### Remove working directory ###")
    client.removeFolder(testEnvName)
    print("### Close connection ###")
    client.close()

    # Exit with 1 if test failed, otherwise 0
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

# Exit with 1 if any command failed (except test)
except Exception as e:
    print("### Exception: %s: %s" % (e.__class__, e))
    print("Err: %s" % sshChannelErr)
    traceback.print_exc()
    try:
        client.close()
    except:
        pass
    sys.exit(1)