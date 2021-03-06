from django.shortcuts import render

import os
import json
import logging

from controller.models import CatalogHistory
from controller.services import device_search
from controller.services import service_utils as svc

from controller.forms import OperationForm
from controller.forms import SearchForm
from controller.serializer import CatalogSerializer
import django_filters
from rest_framework import viewsets
from rest_framework import filters
from rest_framework.views import APIView
from django.http import HttpResponse
from django.http import JsonResponse
from django.http import QueryDict

logger = logging.getLogger('django')
path_prefix = os.getcwd() + '/'

# Class-based views for REST-API
class CatalogViewSet(viewsets.ModelViewSet):
    queryset = CatalogHistory.objects.all()
    serializer_class = CatalogSerializer


class DeviceSearch(APIView):
    def get(self, request):
        if 'qparam' in request.GET:
            logger.info('Device Searching with query to MongoDB ... Provided key is [ {0} ]'.format(request.GET.get('qparam')))
            mongo_key = request.GET.get('qparam')
            search_result = device_search.get_storage_view_from_mongo(user_input=mongo_key)
            return JsonResponse({'result': search_result})
        else:
            return JsonResponse({'result': 'Query parameters not provided. Please add \'?qparam=\' with your URI.'})


class RunAnsible(APIView):
    def post(self, request):
        logger.info('Getting request-bodies and serializing via application REST-API...')
        request_body = CatalogSerializer(data=request.data)
        if request_body.is_valid():
            request_body.save()

            logger.info('Making modifications to ansible configuration file...')
            data = svc.modify_ansible_conf_file(user_input=request.data)

            logger.info('User confirmation accepted. Add and Commit controller/ansible/group_vars/all.yml.')
            git_cmd = '/usr/bin/git add ' + path_prefix + 'controller/ansible/group_vars/all.yml'
            ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)

            logger.info('Started to run ansible-playbook commands !!')

            data_result = []
            ansible_cmd = 'ansible-playbook ' + path_prefix + 'controller/ansible/add_new_volumes.yml'
            ec, stdout, stderr = svc.kick_command_from_django(cmd=ansible_cmd)
            if ec != 0:
                logger.error('Failed to executed ansible command, reverting back the configuration file.')
                git_cmd = '/usr/bin/git reset HEAD ' + path_prefix + 'controller/ansible/group_vars/all.yml'
                ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)
                git_cmd = '/usr/bin/git checkout ' + path_prefix + 'controller/ansible/group_vars/all.yml'
                ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)
                for line in stderr.splitlines():
                    data_result.append(line)
                return HttpResponse(json.dumps({'result': 'Failed during ansible module executing...', 'stdout': data_result}))
            else:
                for line in stdout.splitlines():
                    data_result.append(line)
                # # Updating and commiting the group_vars/all.yml
                # now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                # git_cmd = '/usr/bin/git commit -m \"{0} Operation complete. {1}\"'.format(now, request.data['message'])
                # ec, stdout, stderr = utils.kick_command_from_django(cmd=git_cmd)
                # logger.info('Local git repository updated.')
                return HttpResponse(json.dumps({'result': 'Success !!', 'stdout': data_result}))
        else:
            return HttpResponse(json.dumps({'result': 'Some wrong data provided. Check request-body.'}))


# Functional views for Web UI
def front_main(request):
    view_action = ''
    data_confirm_storage = ''
    data_confirm_server = ''
    data_confirm_switch = ''
    data_result = ''
    result_summary = ''
    mongodb_key = ''
    find_result = []

    search_form = SearchForm()
    ops_form = OperationForm()

    if request.method == 'POST':
        if 'choice' in request.POST:
            search_form = SearchForm()
            view_action = 'select'

        elif 'precheck' in request.POST:
            search_form = SearchForm()
            view_action = 'precheck'

        elif 'search' in request.POST:
            search_form = SearchForm(data=request.POST)
            if search_form.is_valid:
                mongodb_key = str(request.POST['server_name'])
                logger.info('Start device-search for ' + mongodb_key)
                find_result = device_search.get_storage_view_from_mongo(user_input=mongodb_key)
                view_action = 'search_result'

        elif 'start_ops' in request.POST:
            # Default page with blank value
            ops_form = OperationForm()
            view_action = 'operations'

        elif 'confirm' in request.POST:
            ops_form = OperationForm(data=request.POST)
            view_action = 'check_config'
            if ops_form.is_valid():
                logger.info('Making modifications to ansible configuration file...')
                data = svc.modify_ansible_conf_file(user_input=request.POST)
                data_confirm_server, data_confirm_storage, data_confirm_switch = svc.parse_confirm_data(modified_data=data)
                # Throw input data to Django model
                logger.info('Saving catalog data to Django models...')
                CatalogHistory.objects.create(**ops_form.cleaned_data)

                check_result1, check_result2 = svc.get_device_mismatch_check(data=request.POST)
                if check_result1 and check_result2:
                    pass
                else:
                    view_action = 'invalid'

        elif 'back' in request.POST:
            ops_form = OperationForm()
            # Removed records if rollback
            logger.info('Delete the saved data from Django models...')
            CatalogHistory.objects.order_by('-id')[0].delete()

            logger.info('User confirmation declined. Initiatlize operation form, and git checkouted.')
            git_cmd = '/usr/bin/git checkout ' + path_prefix + 'controller/ansible/group_vars/all.yml'
            ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)
            if ec != 0:
                logger.error('Failed to git checkouted.')
            view_action = 'returned'

        elif 'run' in request.POST:
            ops_form = {}
            logger.info('User confirmation accepted. Add and Commit controller/ansible/group_vars/all.yml.')
            git_cmd = '/usr/bin/git add ' + path_prefix + 'controller/ansible/group_vars/all.yml'
            ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)

            logger.info('Started to run ansible-playbook commands !!')

            data_result = []
            ansible_cmd = 'ansible-playbook -vvv ' + path_prefix + 'controller/ansible/add_new_volumes.yml'
            ec, stdout, stderr = svc.kick_command_from_django(cmd=ansible_cmd)
            if ec != 0:
                result_summary = '>>> Ansible Command failed with some errors. '
                logger.error('Failed to executed ansible command, reverting back the configuration file.')
                git_cmd = '/usr/bin/git reset HEAD ' + path_prefix + 'controller/ansible/group_vars/all.yml'
                ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)
                git_cmd = '/usr/bin/git checkout ' + path_prefix + 'controller/ansible/group_vars/all.yml'
                ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)
                for line in stderr.splitlines():
                    data_result.append(line)
            else:
                result_summary = '>>> Successfully Done. Stdout: '
                for line in stdout.splitlines():
                    data_result.append(line)
                # # Updating and commiting the group_vars/all.yml
                # now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                # git_cmd = '/usr/bin/git commit -m \"{0} Operation complete. {1}\"'.format(now, request.data['message'])
                # ec, stdout, stderr = svc.kick_command_from_django(cmd=git_cmd)
                # logger.info('Local git repository updated.')

            view_action = 'run_ansible'

    return render(request, 'home.html',{
        'search_form': search_form,
        'ops_form': ops_form,
        'view_action': view_action,
        'data_confirm_storage': data_confirm_storage,
        'data_confirm_server': data_confirm_server,
        'data_confirm_switch': data_confirm_switch,
        'data_result': data_result,
        'result_summary': result_summary,
        'mongodb_key': mongodb_key,
        'find_result': find_result,
        })


def upload_menu(request):
    return render(request, 'uploads.html')


def history_menu(request):
    c_histories = CatalogHistory.objects.all()
    return render(request, 'histories.html', {
        'histories': c_histories,
    }) 


def catalog_details(request, pk):
    try:
        details = CatalogHistory.objects.get(pk=pk)
    except CatalogHistory.DoesNotExist:
        msg = []
        msg.append('Selected Item does not exist in Django DB.')
        msg.append('Check ID in your URL : \'/history/<ID>\'')
        return render(request, 'redirect.html', {
            'msg': msg
            })
    return render(request, 'details.html', {
        'details': details
        })


def page_not_found(request):
    msg = []
    msg.append('ERROR MESSAGE HERE')
    return render(request, 'redirect.html', {
        'msg': msg
        })
