"""Negotiated controls must reach the real C decoder/planner without affecting V1."""
import json,math,os,subprocess,unittest
from gateway.environment_adapter.translation import translate_environment_action
from gateway.server.service import GatewayError
from protocol.control_v1 import validate_control_message,ProtocolValidationError,WALK_CONTROLS_FEATURE,LOCOMOTION_FEATURE,RUN_GAIT_FEATURE
from Emulator.tests.test_v2_commands import V2CommandsTests

class VariableWalkTests(V2CommandsTests):
    async def test_parameter_delivery_and_update_lifecycle(self):
        connection,socket=self.connection('v2-12servo');connection.features+= (WALK_CONTROLS_FEATURE,)
        action=translate_environment_action({'type':'robotCommand','command':'walk','units':3,'speed':25})
        self.assertEqual(action.params,{'dir':'fwd','steps':3,'speed':25})
        seq=await connection.service.queue_intent(action.name,action.params,robot_id='test-body',received_at=100.)
        await connection._handle_control({'t':'ack','seq':seq})
        action=translate_environment_action({'type':'move','direction':'forward','stride':100,'rate':2,'update':seq})
        update=await connection.service.queue_intent(action.name,action.params,robot_id='test-body',received_at=100.)
        await connection._handle_control({'t':'ack','seq':update})
        self.assertNotIn(update,connection.pending);self.assertIn(seq,connection.pending)
        self.assertEqual(socket.messages[-1]['update'],seq)
        await connection._handle_control({'t':'done','seq':seq})
        with self.assertRaises(GatewayError):await connection.service.queue_intent(action.name,action.params,robot_id='test-body',received_at=100.)

    async def test_controls_never_silently_fall_back(self):
        for model in ['v1-8servo','v2-12servo']:
            c,s=self.connection(model)
            with self.assertRaises(GatewayError):await c.send_command({'t':'intent','name':'walk','dir':'fwd','steps':1,'speed':25},received_at=100.)
            self.assertEqual(s.messages,[]);self.assertEqual(c.next_sequence,1)

    async def test_invalid_control_sets_are_rejected(self):
        cases=[{'speed':True},{'speed':-1},{'speed':201},{'gait':'crawl','speed':101},{'speed':float('nan')},{'stride':50},{'rate':1},
               {'speed':25,'rate':1,'stride':50},{'stride':0,'rate':1},{'stride':100,'rate':0},{'stride':100,'rate':4},
               {'speed_percent':25},{'update':1},{'speed':25,'update':0},{'gait':'swim'}]
        for fields in cases:
            with self.subTest(fields=fields):
                message={'t':'intent','seq':1,'name':'walk','dir':'fwd','steps':3,**fields}
                with self.assertRaises(ProtocolValidationError):validate_control_message(message)
                action={'type':'robotCommand','command':'backward' if fields.get('dir')=='back' else 'walk',**fields}
                self.assertIsNone(translate_environment_action(action))

    async def test_actual_gateway_wire_drives_native_offline_model(self):
        exe=os.environ.get('AINEKIO_V2_WALK_COMMAND')
        if not exe:self.skipTest('set AINEKIO_V2_WALK_COMMAND to compiled offline CLI')
        for speed in [0,25,50,75,100]:
            c,socket=self.connection('v2-12servo');c.features+=(WALK_CONTROLS_FEATURE,)
            action=translate_environment_action({'type':'robotCommand','command':'walk','units':1,'speed':speed})
            await c.service.queue_intent(action.name,action.params,robot_id='test-body',received_at=100.)
            run=subprocess.run([exe,'30000'],input=json.dumps(socket.messages[0])+'\n',capture_output=True,text=True,check=True)
            frames=[json.loads(line) for line in run.stdout.splitlines()]
            self.assertTrue(frames[-1]['complete']);self.assertTrue(all(frames[-1]['grounded']))
            self.assertGreater(len(frames),1)

    async def test_continuous_direction_and_crawl_negotiation(self):
        commands = [("walk","fwd","walk"),("backward","back","walk"),("left","turn_l","walk"),("right","turn_r","walk"),("crawl","fwd","crawl")]
        for name,direction,gait in commands:
            action=translate_environment_action({"type":"robotCommand","command":name,"continuous":True,"speed":25})
            self.assertEqual(action.name,"walk");self.assertEqual(action.params["steps"],0);self.assertEqual(action.params["dir"],direction)
            for feature in [None,WALK_CONTROLS_FEATURE,LOCOMOTION_FEATURE,RUN_GAIT_FEATURE]:
                c,socket=self.connection("v2-12servo");c.capabilities["commands"]=["walk","backward","left","right","crawl","stop"]
                if feature:c.features+=(feature,)
                if feature!=LOCOMOTION_FEATURE:
                    with self.assertRaises(GatewayError):await c.send_command({"t":"intent","name":"walk",**action.params},received_at=100.)
                    self.assertEqual(c.next_sequence,1);self.assertEqual(socket.messages,[]);continue
                seq=await c.send_command({"t":"intent","name":"walk",**action.params},received_at=100.)
                await c._handle_control({"t":"ack","seq":seq})
                for mutation in [{"dir":"back" if direction!="back" else "fwd"},{"gait":"crawl" if gait=="walk" else "walk"}]:
                    before=c.next_sequence
                    with self.assertRaises(GatewayError):await c.send_command({"t":"intent","name":"walk",**action.params,"update":seq,**mutation},received_at=100.)
                    self.assertEqual(c.next_sequence,before)
                finish=await c.send_command({"t":"intent","name":"walk",**action.params,"speed":0,"update":seq},received_at=100.)
                await c._handle_control({"t":"ack","seq":finish})
                self.assertIn(seq,c.pending);self.assertNotIn(finish,c.pending)
                await c._handle_control({"t":"done","seq":seq});self.assertNotIn(seq,c.pending)

    async def test_new_pose_and_crawl_require_declared_support(self):
        for name in ["crouch","crawl"]:
            action=translate_environment_action({"type":"robotCommand","command":name})
            self.assertIsNotNone(action)
            for model,ready in [("v1-8servo",True),("v2-12servo",False),("v2-12servo",True)]:
                c,socket=self.connection(model,ready=ready);c.features+=(LOCOMOTION_FEATURE,)
                with self.assertRaises(GatewayError):await c.service.queue_intent(action.name,action.params,robot_id="test-body",received_at=100.)
                self.assertEqual(socket.messages,[])
        c,socket=self.connection("v2-12servo");c.capabilities["commands"]=["crouch"]
        action=translate_environment_action({"type":"robotCommand","command":"crouch"})
        await c.service.queue_intent(action.name,action.params,robot_id="test-body",received_at=100.)
        self.assertEqual(socket.messages[0]["asset"],"crouch")

    async def test_directional_native_finish_from_gateway_wire(self):
        exe=os.environ.get("AINEKIO_V2_WALK_COMMAND")
        if not exe:self.skipTest("set AINEKIO_V2_WALK_COMMAND to compiled offline CLI")
        for gait in ["walk","crawl"]:
            for direction in ["fwd","back","turn_l","turn_r"]:
                c,socket=self.connection("v2-12servo");c.features+=(LOCOMOTION_FEATURE,)
                c.capabilities["commands"]=["walk","backward","left","right","crawl","stop"]
                params={"dir":direction,"gait":gait,"steps":0,"speed":100}
                seq=await c.service.queue_intent("walk",params,robot_id="test-body",received_at=100.)
                await c._handle_control({"t":"ack","seq":seq})
                await c.service.queue_intent("walk",{**params,"speed":0,"update":seq},robot_id="test-body",received_at=100.)
                run=subprocess.run([exe,"15000"],input=json.dumps(socket.messages[0])+"\n10000 "+json.dumps(socket.messages[1])+"\n",capture_output=True,text=True,check=True)
                frames=[json.loads(line) for line in run.stdout.splitlines()]
                self.assertFalse(frames[999]["complete"]);self.assertTrue(frames[-1]["complete"]);self.assertTrue(all(frames[-1]["grounded"]))
                self.assertAlmostEqual(frames[-1]["body"][2],-35 if gait=="crawl" else -2)

    async def test_run_negotiation_and_legacy_asset(self):
        for model in ['v1-8servo','v2-12servo']:
            for feature in [False,True]:
                c,socket=self.connection(model)
                c.features+=(LOCOMOTION_FEATURE,)
                if feature:c.features+=(RUN_GAIT_FEATURE,)
                if c.capabilities is not None:c.capabilities['commands']=['walk','run','stop']
                message={'t':'intent','name':'walk','dir':'fwd','steps':0,'speed':150}
                if model=='v2-12servo' and feature:
                    await c.send_command(message,received_at=100.)
                    self.assertEqual(socket.messages[-1]['speed'],150)
                else:
                    with self.assertRaises(GatewayError):await c.send_command(message,received_at=100.)
                    self.assertEqual(c.next_sequence,1);self.assertFalse(socket.messages)
        for model in ['v1-8servo','v2-12servo']:
            action=translate_environment_action({'type':'robotCommand','command':'run'},model=model)
            if model=='v1-8servo':self.assertEqual((action.name,action.params),('emote',{'asset':'run'}))
            else:self.assertEqual((action.name,action.params),('walk',{'dir':'fwd','steps':0,'gait':'walk','speed':150}))
        c,socket=self.connection('v2-12servo');c.features+=(LOCOMOTION_FEATURE,RUN_GAIT_FEATURE,);c.capabilities['commands']=['walk','run','stop']
        await c.service.emote('run',robot_id='test-body',received_at=100.)
        self.assertEqual(socket.messages[-1]['name'],'walk');self.assertEqual(socket.messages[-1]['speed'],150)

    async def test_gateway_native_walk_run_walk_finish(self):
        exe=os.environ.get('AINEKIO_V2_WALK_COMMAND')
        if not exe:self.skipTest('set AINEKIO_V2_WALK_COMMAND to compiled offline CLI')
        c,socket=self.connection('v2-12servo');c.features+=(LOCOMOTION_FEATURE,RUN_GAIT_FEATURE,);c.capabilities['commands']=['walk','run','stop']
        params={'dir':'fwd','gait':'walk','steps':0,'speed':100}
        seq=await c.service.queue_intent('walk',params,robot_id='test-body',received_at=100.)
        await c._handle_control({'t':'ack','seq':seq})
        for speed in [150,200,75,0]:
            update=await c.service.queue_intent('walk',{**params,'speed':speed,'update':seq},robot_id='test-body',received_at=100.)
            await c._handle_control({'t':'ack','seq':update})
            self.assertIn(seq,c.pending);self.assertNotIn(update,c.pending)
        wire=json.dumps(socket.messages[0])+'\n'+''.join(str(ms)+' '+json.dumps(msg)+'\n' for ms,msg in zip([6000,14000,20000,28000],socket.messages[1:]))
        result=subprocess.run([exe,'40000','120'],input=wire,text=True,capture_output=True,check=True)
        rows=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(rows[-1]['complete']);self.assertTrue(all(rows[-1]['grounded']))
        self.assertTrue(all(r['run_blend']==0 for r in rows if r['ms']<6000))
        self.assertTrue(all(r['run_blend']==1 for r in rows if 15000<r['ms']<19000))
        self.assertTrue(all(r['run_blend']==0 for r in rows if 26000<r['ms']))
        self.assertTrue(any(not any(r['grounded']) for r in rows))

    async def test_run_schema_matches_python_ranges(self):
        from Slave.software.tests.protocol.test_contracts import assert_matches_schema, SchemaMismatch
        from pathlib import Path
        schema=json.loads((Path(__file__).resolve().parents[2]/'Slave/software/protocol/schemas/control-v1.schema.json').read_text())
        base={'t':'intent','seq':1,'name':'walk','dir':'back','steps':0}
        for fields in [{'gait':'walk','speed':200},{'gait':'run','stride':100,'rate':3},{'gait':'crawl','speed':100}]:
            validate_control_message({**base,**fields});assert_matches_schema({**base,**fields},schema,schema)
        for fields in [{'gait':'crawl','speed':101},{'gait':'walk','speed':201},{'gait':'run','stride':101,'rate':3}]:
            with self.assertRaises(ProtocolValidationError):validate_control_message({**base,**fields})
            with self.assertRaises(SchemaMismatch):assert_matches_schema({**base,**fields},schema,schema)
