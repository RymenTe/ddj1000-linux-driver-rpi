#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"

kernel_version="$(uname -r)"
source_package="linux-hwe-6.17"
work_dir="/tmp/ddj1000-linux-driver-kernel-src"
apt_dir="/tmp/ddj1000-linux-driver-apt"
build_dir="$repo_dir/build/ddj1000-driver"
patch_file="$repo_dir/patches/linux/snd-usb-audio-ddj1000-composite-quirk.patch"
key_file="$build_dir/ddj1000-linux-driver-mok.key"
der_file="$build_dir/ddj1000-linux-driver-mok.der"
module_name="snd-usb-audio-ddj1000.ko"
midi_module_name="snd-usbmidi-lib-test.ko"

usage() {
    cat <<EOF
Usage: $0 [--kernel-version VERSION] [--source-package NAME]

Downloads Ubuntu kernel source into /tmp, applies the DDJ-1000 snd-usb-audio
quirk patch, builds the USB audio modules against the installed kernel headers,
and signs the resulting modules with a local MOK key under build/ddj1000-driver.

This script does not enroll the MOK key. With Secure Boot enabled, run the
printed mokutil command manually, reboot, and enroll the key in the blue MOK UI.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kernel-version)
            kernel_version="$2"
            shift 2
            ;;
        --source-package)
            source_package="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! -d "/lib/modules/$kernel_version/build" ]]; then
    echo "Missing kernel headers: /lib/modules/$kernel_version/build" >&2
    exit 1
fi

mkdir -p "$apt_dir/lists/partial" "$apt_dir/cache/archives/partial" "$work_dir" "$build_dir"

cat > "$apt_dir/ubuntu-src.sources" <<'EOF'
Types: deb-src
URIs: http://de.archive.ubuntu.com/ubuntu/
Suites: noble noble-updates noble-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb-src
URIs: http://security.ubuntu.com/ubuntu/
Suites: noble-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF

apt_opts=(
    -o "Dir::Etc::sourceparts=$apt_dir"
    -o "Dir::Etc::sourcelist=/dev/null"
    -o "Dir::State::lists=$apt_dir/lists"
    -o "Dir::Cache=$apt_dir/cache"
    -o "APT::Get::List-Cleanup=0"
)

echo "Updating temporary deb-src lists..."
apt-get "${apt_opts[@]}" update

echo "Downloading $source_package source into $work_dir..."
(
    cd "$work_dir"
    apt-get "${apt_opts[@]}" source --download-only "$source_package"
)

dsc_file="$(find "$work_dir" -maxdepth 1 -name "${source_package}_*.dsc" | sort -V | tail -n 1)"
if [[ -z "$dsc_file" ]]; then
    echo "No .dsc downloaded for $source_package" >&2
    exit 1
fi

source_dir="$(find "$work_dir" -maxdepth 1 -type d -name "${source_package}-*" | sort -V | tail -n 1)"
if [[ -n "$source_dir" ]]; then
    echo "Removing stale extracted source tree $source_dir..."
    rm -rf "$source_dir"
fi

echo "Extracting $dsc_file..."
(
    cd "$work_dir"
    dpkg-source -x "$dsc_file"
)
source_dir="$(find "$work_dir" -maxdepth 1 -type d -name "${source_package}-*" | sort -V | tail -n 1)"

if [[ -z "$source_dir" || ! -f "$source_dir/sound/usb/quirks-table.h" ]]; then
    echo "Could not locate extracted kernel source with sound/usb/quirks-table.h" >&2
    exit 1
fi

if ! grep -q "0x2b73, 0x0020" "$source_dir/sound/usb/quirks-table.h"; then
    echo "Applying DDJ-1000 quirk patch..."
    patch --batch --forward -d "$source_dir" -p0 < "$patch_file"
else
    echo "DDJ-1000 quirk already present in source tree."
fi

echo "Building sound/usb modules against $kernel_version headers..."
make -C "/lib/modules/$kernel_version/build" M="$source_dir/sound/usb" modules

cp "$source_dir/sound/usb/snd-usb-audio.ko" "$build_dir/$module_name"
cp "$source_dir/sound/usb/snd-usbmidi-lib.ko" "$build_dir/$midi_module_name"

if [[ ! -f "$key_file" || ! -f "$der_file" ]]; then
    echo "Creating local MOK signing key under $build_dir..."
    openssl req \
        -new -x509 -newkey rsa:2048 \
        -keyout "$key_file" \
        -outform DER \
        -out "$der_file" \
        -nodes \
        -days 36500 \
        -subj "/CN=DDJ1000 Linux Driver test module signing/"
fi

sign_file="/usr/src/linux-headers-$kernel_version/scripts/sign-file"
if [[ ! -x "$sign_file" ]]; then
    echo "Missing sign-file helper: $sign_file" >&2
    exit 1
fi

echo "Signing test modules..."
"$sign_file" sha256 "$key_file" "$der_file" "$build_dir/$module_name"
"$sign_file" sha256 "$key_file" "$der_file" "$build_dir/$midi_module_name"

cat <<EOF

Built:
  $build_dir/$module_name
  $build_dir/$midi_module_name

Secure Boot MOK status:
EOF
mokutil --test-key "$der_file" || true

cat <<EOF

If Secure Boot says the key is not enrolled, enroll it manually:
  sudo mokutil --import $der_file

Then reboot. In the blue MOK Manager screen choose:
  Enroll MOK -> Continue -> Yes -> enter the password you set -> Reboot

After reboot, test-load the module with:
  bash scripts/dev/load-ddj1000-snd-usb-audio-test-module.sh
EOF