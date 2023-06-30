#!/usr/bin/python3

import argparse
import os
import subprocess
from pathlib import Path


APT_CONF = Path("apt.conf").absolute()
SOURCE_LIST = Path("source.list").absolute()
CWD = Path(os.getcwd()).absolute()
INTERNAL_IMAGE = "archive-docker"
ARCH_MAP = {
    "amd64": "x86_64",
    "386": "i586",
    "arm64": "aarch64",
    "arm": "armh",
    "ppc64le": "ppc64le",
}


def create_apt_files(arch, branch, date):
    APT_CONF.write_text(
        f"""
Dir::Etc::main "/dev/null";
Dir::Etc::parts "/var/empty";
Dir::Etc::SourceList "{SOURCE_LIST}";
Dir::Etc::SourceParts "/var/empty";
Dir::Etc::preferences "/dev/null";
Dir::Etc::preferencesparts "/var/empty";
""".lstrip()
    )
    repo = "http://ftp.altlinux.org/pub/distributions/ALTLinux"
    if branch == "sisyphus":
        branch = "Sisyphus"
        branch_word = ""
    else:
        branch_word = "/branch"
    SOURCE_LIST.write_text(
        f"""
rpm {repo}/{branch}{branch_word} {ARCH_MAP[arch]} classic
rpm {repo}/{branch}{branch_word} noarch classic
""".lstrip()
    )


def make(arch, branch, out_dir, mkimage_profiles_dir):
    subprocess.run(
        [
            "make",
            f"APTCONF={APT_CONF}",
            f"ARCH={ARCH_MAP[arch]}",
            f"BRANCH={branch}",
            f"IMAGE_OUTDIR={out_dir}",
            f"IMAGE_OUTFILE=alt.tar.xz",
            "ve/docker.tar.xz",
        ],
        cwd=mkimage_profiles_dir,
    )


def build_tarball(arch, branch, date, mkimage_profiles_dir):
    create_apt_files(arch, branch, date)
    out_dir = CWD / arch
    out_dir.mkdir(exist_ok=True)
    make(arch, branch, out_dir, mkimage_profiles_dir)


def remove_manifest(name):
    subprocess.run(
        [
            "buildah",
            "manifest",
            "rm",
            name,
        ],
        check=False,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def remove_image(name):
    subprocess.run(
        [
            "buildah",
            "image",
            "rm",
            name,
        ],
        check=False,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def buildah_build(arch, image):
    remove_image(f"{INTERNAL_IMAGE}-{arch}")
    subprocess.run(
        [
            "buildah",
            "from",
            "--arch",
            arch,
            "--name",
            f"{INTERNAL_IMAGE}-{arch}",
            "scratch",
        ],
    )
    subprocess.run(
        [
            "buildah",
            "add",
            f"{INTERNAL_IMAGE}-{arch}",
            "alt.tar.xz",
            "/",
        ],
        cwd=CWD / arch,
    )
    subprocess.run(
        [
            "buildah",
            "run",
            f"{INTERNAL_IMAGE}-{arch}",
            "sh",
            "-c",
            "true > /etc/security/limits.d/50-defaults.conf",
        ],
    )
    subprocess.run(
        [
            "buildah",
            "config",
            "--cmd",
            '["/bin/bash"]',
            f"{INTERNAL_IMAGE}-{arch}",
        ],
    )
    subprocess.run(
        [
            "buildah",
            "commit",
            "--rm",
            "--manifest",
            image,
            f"{INTERNAL_IMAGE}-{arch}",
        ],
    )


def podman_push(image):
    subprocess.run(
        [
            "podman",
            "manifest",
            "push",
            image,
            f"docker://{image}",
        ],
    )


def build_all(
    arches, branches, dates, mkimage_profiles_dir, registry, organization, name, stages
):
    repo = f"{registry}/{organization}"
    for branch in branches:
        for date in dates:
            image = f"{repo}/{name}:{branch}-{date}"
            if "build_image" in stages:
                remove_manifest(image)
            for arch in arches:
                if "build_tarball" in stages:
                    build_tarball(arch, branch, date, mkimage_profiles_dir)
                if "build_image" in stages:
                    buildah_build(arch, image)
            if "push" in stages:
                podman_push(image)


def clean():
    subprocess.run(
        [
            "podman",
            "system",
            "prune",
            "-af",
        ],
    )


def parse_args():
    stages = ["build_tarball", "build_image", "push", "clean"]
    all_arches = ["amd64", "386", "arm64", "arm", "ppc64le"]
    default_arches = ["amd64", "arm64"]
    all_branches = ["p9", "p10", "sisyphus"]
    default_branches = ["p10", "sisyphus"]

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-r",
        "--registry",
        default="registry.altlinux.org",
    )
    parser.add_argument(
        "--mkimage-profiles-dir",
        default=Path("~/build/mkimage-profiles").expanduser(),
    )
    parser.add_argument(
        "-o",
        "--organization",
        required=True,
    )
    parser.add_argument(
        "-n",
        "--name",
        default="archive",
    )
    parser.add_argument(
        "-d",
        "--dates",
        nargs="+",
        help="list of dates",
    )
    parser.add_argument(
        "-a",
        "--arches",
        nargs="+",
        default=default_arches,
        choices=all_arches,
        help="list of arches",
    )
    parser.add_argument(
        "--skip-arches",
        nargs="+",
        default=[],
        choices=all_arches,
        help="list of skipping arches",
    )
    parser.add_argument(
        "-b",
        "--branches",
        nargs="+",
        default=default_branches,
        choices=all_branches,
        help="list of branches",
    )
    parser.add_argument(
        "--skip-branches",
        nargs="+",
        default=[],
        choices=all_arches,
        help="list of skipping branches",
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        default=stages,
        choices=stages,
        help="list of stages",
    )
    parser.add_argument(
        "--skip-stages",
        nargs="+",
        default=[],
        choices=stages,
        help="list of skipping stages",
    )
    args = parser.parse_args()

    args.arches = set(args.arches) - set(args.skip_arches)
    args.branches = set(args.branches) - set(args.skip_branches)
    args.stages = set(args.stages) - set(args.skip_stages)

    return args


def main():
    args = parse_args()
    stages = args.stages
    build_all(
        args.arches,
        args.branches,
        args.dates,
        args.mkimage_profiles_dir,
        args.registry,
        args.organization,
        args.name,
        stages,
    )

    if "clean" in stages:
        clean()


if __name__ == "__main__":
    main()
