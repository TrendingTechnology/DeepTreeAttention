#Test main
import pytest
import os
import rasterio
import numpy as np
from DeepTreeAttention import main
from DeepTreeAttention.generators import make_dataset
from matplotlib.pyplot import imshow
from DeepTreeAttention.visualization import visualize
from DeepTreeAttention.utils import metrics
from tensorflow.keras import metrics as keras_metrics

@pytest.fixture()
def ground_truth_raster(tmp_path):
    fn = os.path.join(tmp_path,"ground_truth.tif")
    #Create a raster that looks data (smaller)
    arr = np.random.randint(1,21,size=(1, 30,30)).astype(np.uint16)
    
    #hard coded from Houston 2018 ground truth
    new_dataset = rasterio.open(fn, 'w', driver='GTiff',
                                height = arr.shape[1], width = arr.shape[2],
                                count=arr.shape[0], dtype="uint16",
                                crs=rasterio.crs.CRS.from_epsg("26915"),
                                transform=rasterio.transform.from_origin(272056.0, 3289689.0, 0.5, -0.5))
    
    new_dataset.write(arr)
    new_dataset.close()

    return fn

@pytest.fixture()
def training_raster(tmp_path):
    fn = os.path.join(tmp_path,"training.tif")
    
    #Create a raster that looks data, index order to help id
    arr = np.arange(15 * 15).reshape((15,15))
    arr = np.dstack([arr]*4)
    arr = np.rollaxis(arr, 2,0)
    arr = arr.astype("uint16")
    
    #hard coded from Houston 2018 ground truth
    new_dataset = rasterio.open(fn, 'w', driver='GTiff',
                                height = arr.shape[1], width = arr.shape[2],
                                count=arr.shape[0], dtype="uint16",
                                crs=rasterio.crs.CRS.from_epsg("26915"),
                                transform=rasterio.transform.from_origin(272056.0, 3289689.0, 1, -1))
    
    new_dataset.write(arr)
    new_dataset.close()

    return fn

@pytest.fixture()
def predict_raster(tmp_path):
    fn = os.path.join(tmp_path,"training.tif")
    
    #Create a raster that looks data, index order to help id
    arr = np.arange(12 * 15).reshape((12,15))
    arr = np.dstack([arr]*4)
    arr = np.rollaxis(arr, 2,0)
    arr = arr.astype("uint16")
    
    #hard coded from Houston 2018 ground truth
    new_dataset = rasterio.open(fn, 'w', driver='GTiff',
                                height = arr.shape[1], width = arr.shape[2],
                                count=arr.shape[0], dtype="uint16",
                                crs=rasterio.crs.CRS.from_epsg("26915"),
                                transform=rasterio.transform.from_origin(272056.0, 3289689.0, 1, -1))
    
    new_dataset.write(arr)
    new_dataset.close()

    return fn

@pytest.fixture()
def tfrecords(training_raster, ground_truth_raster,tmpdir):
    tfrecords = make_dataset.generate_training(training_raster, ground_truth_raster, size=5, savedir=tmpdir,chunk_size=100)
    
    return os.path.dirname(tfrecords[0])

@pytest.fixture()
def predict_tfrecords(predict_raster,tmpdir):
    tfrecords = make_dataset.generate_prediction(predict_raster, savedir=tmpdir, size=5, chunk_size=100)
    return tfrecords

@pytest.fixture()
def test_config(tfrecords):
    config = {}
    train_config = { }
    train_config["tfrecords"] = tfrecords
    train_config["batch_size"] = 32
    train_config["epochs"] = 1
    train_config["steps"] = 2
    train_config["crop_size"] = 5
    train_config["sensor_channels"] = 4
    train_config["shuffle"] = False
        
    #evaluation
    eval_config = { }
    eval_config["tfrecords"] = tfrecords
    eval_config["steps"] = 2
    
    config["train"] = train_config
    config["evaluation"] = eval_config
    
    return config

@pytest.mark.parametrize("validation_split",[False, True])
def test_AttentionModel(test_config,validation_split):

    #Create class
    mod = main.AttentionModel()      
    
    #Replace config for testing env
    for key, value in test_config.items():
        for nested_key, nested_value in value.items():
            mod.config[key][nested_key] = nested_value
        
    #Create model
    mod.create()
    mod.read_data(validation_split=validation_split)
        
    #initial weights
    initial_weight = mod.model.layers[1].get_weights()
    
    #How many batches
    if validation_split:
        train_counter =0
        for data, label in mod.train_split:
            print(data.shape)        
            train_counter+=data.shape[0]
                
        test_counter =0
        for data, label in mod.val_split:
            print(data.shape)        
            test_counter+=data.shape[0]
        
        assert train_counter > test_counter
    
    #train
    mod.train()
    
    final_weight = mod.model.layers[1].get_weights()
    
    #assert training took place
    assert not np.array_equal(final_weight,initial_weight)
    
    #assert val acc exists if split
    if validation_split:
        assert "val_acc" in list(mod.model.history.history.keys()) 
        
def test_predict(test_config, predict_tfrecords):
    #Create class
    mod = main.AttentionModel()    
    
    #Replace config for testing env
    for key, value in test_config.items():
        for nested_key, nested_value in value.items():
            mod.config[key][nested_key] = nested_value
    
    #Create
    mod.create()
    mod.read_data()
    results = mod.predict(predict_tfrecords, batch_size=2)
    predicted_raster = visualize.create_raster(results)
    
    #Equals size of the input raster
    assert predicted_raster.shape == (12,15)
    
def test_evaluate(test_config):
    #Create class
    mod = main.AttentionModel()    
    
    #Replace config for testing env
    for key, value in test_config.items():
        for nested_key, nested_value in value.items():
            mod.config[key][nested_key] = nested_value
    
    #Create
    mod.create()
    mod.read_data(validation_split=True)
    
    #Method 1, class eval method
    print("Before evaluation")
    y_pred, y_true = mod.evaluate(mod.val_split)
    
    print("evaluated")
    
    test_acc = keras_metrics.CategoricalAccuracy()
    test_acc.update_state(y_true=y_true, y_pred = y_pred)
    method1_eval_accuracy = test_acc.result().numpy()
    
    assert y_pred.shape == y_true.shape

    #Method 2, keras eval method
    metric_list = mod.model.evaluate(mod.val_split)
    metric_dict = {}
    for index, value in enumerate(metric_list):
        metric_dict[mod.model.metrics_names[index]] = value
    
    assert method1_eval_accuracy == metric_dict["acc"]   
    
    #F1 requires integer, not softmax
    f1s = metrics.f1_scores( y_true, y_pred)    
    