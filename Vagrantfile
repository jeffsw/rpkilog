Vagrant.configure("2") do |config|
    # main rpkilog ubuntu 20.04 VM
    config.vm.define "rpkilog", primary: true, autostart: true do |cf|
        cf.vm.hostname = "rpkilog"
        cf.vm.box = "ubuntu/focal64"
        cf.vm.synced_folder ".", "/rpkilog", type: "virtualbox"
        cf.vm.provider "virtualbox" do |vb|
            vb.gui = false
            vb.memory = 512
            vb.cpus = 1
        end
    end
end
