# @Time : 2021/3/15 9:21
# @Author : Cheng Zhu
# @site : https://gitee.com/lonekey
# @File : makeDataset.py


import os
import sys
from data_model import *
import pickle
import pandas as pd
from utils.git import diff, checkout_this
from utils.file import getFileList
import threading
import json
import time
import copy
from tqdm import tqdm
from shutil import copytree
from utils.log import log
import multiprocessing


sys.setrecursionlimit(1000000)
lock = threading.Lock()


def add_change(code_path, project: Project, prior_commit: Commit, this_commit: Commit):
    # this commit 开始
    file_add_list = diff(code_path, prior_commit.commit_id, this_commit.commit_id, "A")
    file_modified_list = diff(code_path, prior_commit.commit_id, this_commit.commit_id, "M")
    file_del_list = diff(code_path, prior_commit.commit_id, this_commit.commit_id, "D")
    # log('A', len(file_add_list), end='\t\t')
    # log('M', len(file_modified_list), end='\t\t')
    # log('D', len(file_del_list))
    this_commit.current_files = copy.deepcopy(prior_commit.current_files)
    # log(len(this_commit.current_files))

    for delete_file in file_del_list:
        for b_file_id in this_commit.current_files.copy():
            b_file = project.files[b_file_id]
            if b_file.filename == delete_file:
                this_commit.current_files.remove(b_file.id)
                this_commit.D.add(b_file.id)
                this_commit.methods.update(b_file.method_list)

    for add_file in file_add_list:
        file = File(project, add_file)
        project.files[file.id] = file
        this_commit.current_files.add(file.id)
        this_commit.A.add(file.id)
        this_commit.methods.update(file.method_list)

    for modified_file in file_modified_list:
        file = File(project, modified_file)
        project.files[file.id] = file
        for b_file_id in this_commit.current_files.copy():
            b_file = project.files[b_file_id]
            if b_file.filename == modified_file:
                this_commit.A.add(file.id)
                this_commit.D.add(b_file.id)
                this_commit.current_files.remove(b_file.id)
                this_commit.current_files.add(file.id)
                changed_methods = compare_file(project, b_file, file)
                this_commit.methods.update(changed_methods)
                break


    # log(len(this_commit.current_files))
    return this_commit


def get_description_by_bug_id(project: str, bug_id: str):
    with open(f"bug_info/{project}/{project}_description.json", 'r') as f:
        descriptions = json.load(f)
        f.close()
    bug_description = descriptions[bug_id]
    return str(bug_description)


def make_pkl(product, raw_project_path, max_dataset_size, hasBugRepo):
    project = Project(product)

    gl = pd.read_csv(open(f'cache/{product}/git_log.csv', encoding='utf-8'), keep_default_na=False)
    gl = gl.sort_values(by=['Date'])
    fullCommitList = gl.commit.tolist()
    fullDateList = gl.Date.tolist()
    work_list = []
    if hasBugRepo:
        bls = json.load(open(f"cache/{product}/bug_repo.json", 'r'))
        commitList = []
        for item in bls.values():
            for commit_id, commit_time in item['fixCommit'].items():
                commitList.append((commit_id, item['id'], commit_time))
        max_dataset_size = int(max_dataset_size)
        max_dataset_size = min(max_dataset_size, len(commitList))
        log(f"total fix commit {len(commitList)}, use {max_dataset_size}")
        commitList = sorted(commitList, key= lambda x: x[2])[:max_dataset_size]
        commitIdList,_,_ = zip(*commitList)

        for i in range(len(fullCommitList)):
            if fullCommitList[i] in commitIdList or i + 1 < len(fullCommitList) and fullCommitList[i + 1] in commitIdList:
                work_list.append(i)
    else:
        work_list.append(len(fullCommitList)-1)

    # first commit
    commit_id = fullCommitList[work_list[0]]
    commit_date = fullDateList[work_list[0]]

    code_path = f'cache/{product}/code'
    if not os.path.exists(code_path):
        log('copying...')
        copytree(raw_project_path, code_path)
    log('checking to', commit_id)
    checkout_this(code_path, commit_id)

    commit = Commit(commit_id, commit_date)
    thread_list = []
    file_list = getFileList(code_path)
    for file_name in tqdm(file_list, desc=f"[{product}] first version files"):
        thread = myThread(project, commit, file_name)
        thread_list.append(thread)
        thread.start()
    while len(thread_list) != 0:
        if not thread_list[-1].is_alive():
            thread_list.pop()
        else:
            time.sleep(1)
    project.commits[commit_id] = commit
    # End first commit
    if hasBugRepo:
        bls = json.load(open(f"cache/{product}/bug_repo.json", 'r'))
        temp_commit = commit
        for i in tqdm(range(len(work_list)), desc=f"[{product}] commits"):
            if i == 0:
                continue
            commit_id = fullCommitList[work_list[i]]
            checkout_this(code_path, commit_id)
            commit_date = fullDateList[work_list[i]]
            commit = Commit(commit_id, commit_date)
            commit = add_change(code_path, project, temp_commit, commit)
            project.commits[commit.commit_id] = commit
            for k, v in bls.items():
                if commit_id in v["fixCommit"].keys():
                    if k not in project.bugs.keys():
                        new_bug = Bug(k, temp_commit.commit_id, commit.commit_id, v["summary"], v["description"]["comment"], v["comments"])
                    else:
                        new_bug = project.bugs[k]
                        new_bug.fixed_version.append(commit.commit_id)
                    project.bugs[v["id"]] = new_bug
                    break
            temp_commit = commit
    with open(f"cache/{product}/{product}.pkl", 'wb') as f1:
        pickle.dump(project, f1, protocol=4)
    f1.close()


class myThread(threading.Thread):
    def __init__(self, project: Project, commit: Commit, file_name):
        threading.Thread.__init__(self)
        self.project = project
        self.commit = commit
        self.file_name = file_name

    def run(self):
        file = File(self.project, self.file_name, lock)
        lock.acquire()
        self.project.files[file.id] = file
        self.commit.current_files.add(file.id)
        lock.release()


def compare_file(project: Project, b_file: File, file: File):
    buggy_methods = []
    for m1_id in b_file.method_list:
        changed = True
        m1 = project.methods[m1_id]
        for m2_id in file.method_list:
            m2 = project.methods[m2_id]
            if m1.method_name == m2.method_name and m1.content == m2.content:
                changed = False
                break
        if changed:
            buggy_methods.append(m1_id)
    for m2_id in file.method_list:
        m2 = project.methods[m2_id]
        if m2.method_name not in [project.methods[m1].method_name for m1 in b_file.method_list]:
            buggy_methods.append(m2_id)
    return buggy_methods


if __name__ == "__main__":
    # PROJECT_LIST = ["AspectJ", "Eclipse_Platform_UI", "Birt", "JDT", "SWT", "Tomcat"]
    # for p in PROJECT_LIST:
    #     process = multiprocessing.Process(target=make_pkl, args=(p, f'cache/{p}/code', 600))
    #     process.start()

    p: Project = pickle.load(open('cache/platform/platform.pkl', 'rb'))
    log(len(p.files), len(p.methods), len(p.commits), len(p.bugs))
    for f in p.files.values():
        log(f.filename)
    # for fileId in p.commits[p.bugs["28942"].bug_exist_version].current_files:
    #     file = p.files[fileId]
    #     if file.filename.find("org.eclipse.jdt.ui/core refactoring/org/eclipse/jdt/internal/corext/refactoring/code/ExtractMethodAnalyzer.java") != -1:
    #         log(fileId, file.filename, len(file.method_list))

    # p.getBuggyCodes()
    # log(p.commits.values())
    # for i in p.getBugIds():
    #     log(i, p.bugs[i].fixed_version)
    # log(p.bugs.keys())
    # a = p.getChangedFilesByBugID('391123')
    # for i in a:
    #     log(i)