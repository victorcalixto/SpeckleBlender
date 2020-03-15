import bpy, bmesh,os
from bpy.props import StringProperty, BoolProperty, FloatProperty, CollectionProperty, EnumProperty

from speckle import SpeckleApiClient
from bpy_speckle.convert import to_speckle_object
from bpy_speckle.convert.to_speckle import export_ngons_as_polylines

from .accounts import get_scale_length
#from speckle import SpeckleResource

#from ..operators import get_available_streams, initialize_speckle_client

class SpeckleUpdateObject(bpy.types.Operator):
    bl_idname = "object.speckle_update"
    bl_label = "Speckle - Update Object"
    bl_options = {'REGISTER', 'UNDO'}

    client = None

    def execute(self, context):
        client = context.scene.speckle_client
        account = context.scene.speckle.accounts[context.scene.speckle.active_account]
        stream = account.streams[account.active_stream]

        client.server = account.server
        client.s.headers.update({'Authorization': account.authToken})   
        
        active = context.active_object
        print(active)
        if active is not None:
            if active.speckle.enabled:
                if active.speckle.send_or_receive == "send" and active.speckle.stream_id:
                    res = client.StreamGetAsync(active.speckle.stream_id)['resource']
                    #res = client.streams.get(active.speckle.stream_id)
                    print(res)
                    if res is None:
                        print ("Getting stream failed.")
                        return {'CANCELLED'}

                    scale = context.scene.unit_settings.scale_length / get_scale_length(res['baseProperties']['units'])

                    sm = to_speckle_object(active, scale)

                    print("Updating object {}".format(sm['_id']))
                    client.objects.update(active.speckle.object_id, sm)

                    return {'FINISHED'}

                    res = client.ObjectCreateAsync([sm])
                    new_id = res['resources'][0]['_id']

                    for o in stream_data['objects']:
                        if o['_id'] == active.speckle.object_id:
                            o['_id'] = new_id
                            break

                    res = client.StreamUpdateAsync(active.speckle.stream_id, {'objects': stream_data['objects']})
                    res = client.ObjectDeleteAsync(active.speckle.object_id)
                    active.speckle.object_id = new_id

                    if res == None: return {'CANCELLED'}
            return {'FINISHED'}
        return {'CANCELLED'}            


class SpeckleResetObject(bpy.types.Operator):
    bl_idname = "object.speckle_reset"
    bl_label = "Speckle - Reset Object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        context.object.speckle.send_or_receive = "send"
        context.object.speckle.stream_id = ""
        context.object.speckle.object_id = ""
        context.object.speckle.enabled = False
        context.scene.update()

        return {'FINISHED'}

class SpeckleDeleteObject(bpy.types.Operator):
    bl_idname = "object.speckle_delete"
    bl_label = "Speckle - Delete Object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active = context.object
        if active.speckle.enabled:
            res = context.scene.speckle_client.StreamGetAsync(active.speckle.stream_id)
            existing = [x for x in res['resource']['objects'] if x['_id'] == active.speckle.object_id]
            if existing == None:
                return {'CANCELLED'}
            #print("Existing: %s" % SpeckleResource.to_json_pretty(existing))
            new_objects = [x for x in res['resource']['objects'] if x['_id'] != active.speckle.object_id]
            #print (SpeckleResource.to_json_pretty(new_objects))

            res = context.scene.speckle_client.GetLayers(active.speckle.stream_id)
            new_layers = res['resource']['layers']
            new_layers[-1]['objectCount'] = new_layers[-1]['objectCount'] - 1
            new_layers[-1]['topology'] = "0-%s" % new_layers[-1]['objectCount']

            res = context.scene.speckle_client.StreamUpdateAsync({"objects":new_objects, "layers":new_layers}, active.speckle.stream_id)
            res = context.scene.speckle_client.ObjectDeleteAsync(active.speckle.object_id)

            active.speckle.send_or_receive = "send"
            active.speckle.stream_id = ""
            active.speckle.object_id = ""
            active.speckle.enabled = False
            context.scene.update()

        return {'FINISHED'}


class SpeckleUploadNgonsAsPolylines(bpy.types.Operator):
    bl_idname = "object.speckle_upload_ngons_as_polylines"
    bl_label = "Speckle - Upload Ngons As Polylines"
    bl_options = {'REGISTER', 'UNDO'}

    clear_stream: BoolProperty(
        name="Clear stream", 
        default=False,
        )


    def execute(self, context):

        active = context.active_object
        if active is not None and active.type == 'MESH':
            # If active object is mesh


            client = context.scene.speckle_client
            client.verbose = True
            account = context.scene.speckle.accounts[context.scene.speckle.active_account]
            stream =account.streams[account.active_stream]

            client.server = account.server
            client.s.headers.update({
                'content-type': 'application/json',
                'Authorization': account.authToken,
            })            

            scale = context.scene.unit_settings.scale_length / get_scale_length(stream.units)

            sp = export_ngons_as_polylines(active, scale)

            if sp is None:
                return {'CANCELLED'}

            placeholders = []
            for polyline in sp:

                #res = client.objects.create(polyline)[0]
                res = client.ObjectCreateAsync([polyline])['resources'][0]
                print(res)

                if res == None: 
                    print(client.me)
                    continue

                polyline['_id'] = res['_id']
                placeholders.append({'type':'Placeholder', '_id':res['_id']})

            if len(placeholders) < 1:
                return {'CANCELLED'}

                # Get list of existing objects in stream and append new object to list
            print("Fetching stream...")            
            res = client.StreamGetAsync(stream.streamId)
            if res is None: return {'CANCELLED'}

            stream = res['resource']
            if '_id' in stream.keys():
                del stream['_id']

            if self.clear_stream:
                print("Clearing stream...")
                stream['objects'] = placeholders
                N = 0
            else:
                stream['objects'].extend(placeholders)

            N = stream['layers'][-1]['objectCount']
            if self.clear_stream:
                N = 0
            stream['layers'][-1]['objectCount'] = N + len(placeholders)
            stream['layers'][-1]['topology'] = "0-%s" % (N + len(placeholders))

            res = client.StreamUpdateAsync(stream['streamId'], {'objects':stream['objects'], 'layers':stream['layers']})

            # Update view layer
            context.view_layer.update()
            print("Done.")

        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)   

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "clear_stream")

class SpeckleUploadObject(bpy.types.Operator):
    bl_idname = "object.speckle_upload_object"
    bl_label = "Speckle - Upload Object"
    bl_options = {'REGISTER', 'UNDO'}


    def execute(self, context):

        active = context.active_object
        if active is not None:
            # If active object is mesh

            client = context.scene.speckle_client
            client.verbose = True
            account = context.scene.speckle.accounts[context.scene.speckle.active_account]
            stream =account.streams[account.active_stream]

            client.server = account.server
            client.s.headers.update({
                'content-type': 'application/json',
                'Authorization': account.authToken,
            })            

            print("authToken: ", account.authToken)

            scale = context.scene.unit_settings.scale_length / get_scale_length(stream.units)

            sm = to_speckle_object(active, scale)

            if '_id' in sm.keys():
                del sm['_id']

            if 'transform' in sm.keys():
                del sm['transform']

            if 'properties' in sm.keys():
                del sm['properties']

            #res = client.objects.create(sm)
            res = client.ObjectCreateAsync([polyline])
            if res == None: return {'CANCELLED'}

            sm['_id'] = res['resources'][0]['_id']
            pl = {'type':'Placeholder', '_id':res['resources'][0]['_id']}

            # Get list of existing objects in stream and append new object to list
            print("Fetching stream...")            
            res = client.StreamGetAsync(stream.streamId)
            #res = client.streams.get(stream.streamId)
            if res is None: return {'CANCELLED'}

            stream = res['resource']
            if '_id' in stream.keys():
                del stream['_id']

            stream['objects'].append(pl)

            N = stream['layers'][-1]['objectCount']
            stream['layers'][-1]['objectCount'] = N + 1
            stream['layers'][-1]['topology'] = "0-%s" % (N + 1)

            print("Updating stream %s" % stream['streamId'])

            res = client.StreamUpdateAsync(stream['streamId'], {'objects':stream['objects'], 'layers':stream['layers']})
            #res = client.streams.update(stream['streamId'], {'objects':stream['objects'], 'layers':stream['layers']})
            print(res)

            active.speckle.enabled = True
            active.speckle.object_id = sm['_id']
            active.speckle.stream_id = stream['streamId']
            active.speckle.send_or_receive = 'send'

            # Update view layer
            context.view_layer.update()
            print("Done.")

        return {'FINISHED'}    
     